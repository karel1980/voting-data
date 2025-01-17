import glob
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup
from nltk.tokenize import WhitespaceTokenizer
from pypdf import PdfReader

from model import Motion, Proposal, VoteType
from src.model import MotionId

logger = logging.getLogger(__name__)


class FederalChamberVotingPdfExtractor():
	"""
	Extract voting behavior from a voting report on the Belgian federal chamber's website,
	for example at https://www.dekamer.be/kvvcr/showpage.cfm?section=/flwb/recent&language=nl&cfm=/site/wwwcfm/flwb/LastDocument.cfm.
	"""

	def print_page(self, voting_report: str, page_number: int) -> None:
		"""
		Print a specific page from a voting report.
		This allows inspecting it in the way it has been processed by pypdf,
		as a means to understand how to process certain parts in code below,
		or to understand why code below is not working as expected.
		"""
		pdf_reader = PdfReader(voting_report)
		print(pdf_reader.pages[
				  page_number - 1].extract_text())  # index selection based on page_number: indexing is 0-based of course!

	def extract(self, voting_report: str) -> List[Motion]:
		logger.info("Starting extraction on %s", voting_report)
		pdf_reader = PdfReader(voting_report)

		# Find out where the sections of the document start, because they will each be processed differently further below:
		first_page_idx_of_votes, first_page_idx_of_votes_by_name = self.find_start_pages(pdf_reader)

		# Extract the voting on proposals: how much yes, how much no, etc.
		proposals = self.extract_votes(pdf_reader, first_page_idx_of_votes)

		# Extract the voting on proposals by name of individual politicians:
		motions = self.extract_votes_by_name(pdf_reader, voting_report, first_page_idx_of_votes_by_name, proposals)

		return motions

	def find_start_pages(self, pdf_reader: PdfReader) -> Tuple[int, int]:
		logging.debug("Finding start pages of important sections in the document.")
		first_page_idx_of_votes = None
		first_page_idx_of_votes_by_name = None
		for page_idx, page in enumerate(pdf_reader.pages):
			page_text = page.extract_text()
			if self.is_page_containing_votes(page_text):
				if first_page_idx_of_votes is None:
					first_page_idx_of_votes = page_idx

			if self.is_page_containing_votes_by_name(page_text):
				if first_page_idx_of_votes_by_name is None:
					first_page_idx_of_votes_by_name = page_idx

		if first_page_idx_of_votes is None:
			raise RuntimeError("No page with votes could be found.")
		if first_page_idx_of_votes_by_name is None:
			raise RuntimeError("No page with votes by name could be found.")
		logging.debug(f"First page number of votes: {first_page_idx_of_votes + 1}.")
		logging.debug(f"First page number of votes by name: {first_page_idx_of_votes_by_name + 1}.")
		return first_page_idx_of_votes, first_page_idx_of_votes_by_name

	def is_page_containing_votes(self, page_text: str) -> bool:
		return "(Stemming/vote " in page_text

	def is_page_containing_votes_by_name(self, page_text: str) -> bool:
		return "DETAIL VAN DE NAAMSTEMMINGEN" in page_text \
			or "DETAIL DES VOTES NOMINATIFS" in page_text \
			or "DETAIL VAN DE NAAMST EMMINGEN" in page_text \
			or "DETAIL DES VOTES NOM INATIFS" in page_text \
			or "Naamstemming:" in page_text \
			or "Vote nominatif -" in page_text

	def extract_votes(self, pdf_reader: PdfReader, first_page_idx_of_votes: int) -> List[Proposal]:
		proposal_number: Optional[int] = None
		proposal_description_lines: Optional[list] = None
		number_of_last_proposal_saved = -1
		proposals = []
		for page_idx, page in enumerate(pdf_reader.pages[first_page_idx_of_votes:]):
			logging.debug(f"Processing page number {first_page_idx_of_votes + page_idx + 1}.")
			page_text = page.extract_text()
			if self.is_page_containing_votes(page_text):
				for page_line in page_text.split('\n'):

					# If we detect a proposal that is voted:
					match = re.match(r"(\d{2})\s(.*)",
									 page_line)  # line might start with 2 digits, indicating the number of the law to vote.
					if match is not None and len(match.groups()) == 2:

						# If it is a new proposal:
						if int(match.groups()[0]) != proposal_number:
							logging.debug("Found a new proposal.")
							# Start extraction of the proposal number and description.
							proposal_number = int(match.groups()[0])
							logging.debug(f"Extracted vote number: #{proposal_number}.")
							proposal_description_lines = [
								match.groups()[1]
								# The vote description starts immediately on the same line, after the number of the vote.
							]
							proposal_description = None  # we'll set this later, when all vote_description_lines are gathered.

						# If the vote number re-occurs, this is to introduce the proposal description in a second language,
						# let's capture that and add it to the proposal we are currently processing:
						else:
							proposal_description_lines.append("\r\n\r\n" + match.groups()[1])

					# All lines coming after the detection of a vote, if they don't start mentioning voting amounts (amount of yes votes, etc.) and if they are not empty,
					# are parts of the vote description that we want to remember:
					elif proposal_number is not None and not page_line.startswith(
							"(Stemming/vote") and self.is_not_empty_line(page_line):
						# A new line of vote description is to be added for later processing:
						proposal_description_lines.append(page_line)

					# If the page line starts mentioning voting amounts (amount of yes votes, etc.):
					# then finish processing the processing of the vote and save it.
					elif page_line.startswith("(Stemming/vote"):
						# If the proposal has not yet been saved:
						# (this is a protection against saving the proposal multiple times, when "(Stemming/vote)" appears multiple times, due to voting on amendments.)
						if number_of_last_proposal_saved < proposal_number:
							logging.debug("Finishing processing of the proposal vote.")
							proposal_description = \
								(" ".join(proposal_description_lines)).split("Quelqu'un demande -t-il la parole")[
									0].split(
									"Vraagt iemand het woord")[0].split("Stemming over amendement")[0]
							logging.info(f"Saving proposal # {proposal_number}.")
							logging.info(f"Description: {proposal_description}.")
							proposals.append(Proposal(proposal_number, proposal_description))
							number_of_last_proposal_saved = proposal_number

			else:
				# The current page does not contain votes anymore. Stop processing next pages.
				break

		return proposals

	def extract_votes_by_name(self, pdf_reader: PdfReader, report: str, first_page_idx_of_votes_by_name: int,
							  proposals: List[Proposal]) -> List[Motion]:
		current_vote_type: Optional[VoteType] = None
		vote_number: Optional[int] = None
		vote_cancelled: bool = False
		num_votes_yes: Optional[int] = None
		vote_names_yes: Optional[list] = None
		num_votes_no: Optional[int] = None
		vote_names_no: Optional[list] = None
		num_votes_abstention: Optional[int] = None
		vote_names_abstention: Optional[list] = None
		vote_names_lines: Optional[list] = None
		motions: List[Motion] = []

		for page_idx, page in enumerate(pdf_reader.pages[first_page_idx_of_votes_by_name:]):
			logging.debug(f"Processing page number {first_page_idx_of_votes_by_name + page_idx + 1}.")
			page_text = page.extract_text()
			if self.is_page_containing_votes_by_name(page_text):
				for page_line in page_text.split('\n'):
					if "Vote nominatif" in page_line or "Naamstemming:" in page_line:  # or instead of and, to be more robust against things like "Naa mstemming:"
						logging.debug("Found a new vote.")
						# If this is not the first vote in the document, first finish processing of the preceding vote.
						logging.debug("Finishing processing of previous vote.")
						if current_vote_type == VoteType.ABSTENTION:
							# Finishing processing of abstention votes: (if we have already started processing an earlier vote.)
							logging.debug("Finishing processing of abstention votes.")
							vote_names_abstention = self.get_politician_names(vote_names_lines)

							# Saving the vote we just finished processing:
							logging.info(f"Cancelled: {vote_cancelled}.")
							logging.info(f"Yes votes: {num_votes_yes}, by {vote_names_yes}.")
							logging.info(f"No votes: {num_votes_no}, by {vote_names_no}.")
							logging.info(f"Abstention votes: {num_votes_abstention}, by {vote_names_abstention}.")
							logging.info("-" * 50)

							matching_proposals = [proposal for proposal in proposals if proposal.number == vote_number]
							if len(matching_proposals) == 1:
								motion = Motion(MotionId(report, len(motions) + 1), matching_proposals[0], num_votes_yes, vote_names_yes, num_votes_no,
												vote_names_no, num_votes_abstention, vote_names_abstention,
												vote_cancelled)
								logging.info(f"Saving vote # {vote_number}: {motion}.")
								motions.append(motion)

						# Processing the new vote:
						logging.debug("Processing the new vote.")
						if "annulé" in page_line or "geannuleerd" in page_line:
							vote_cancelled = True
							logging.debug("Vote was found to be cancelled.")
							vote_number = int(page_line.rstrip().split(' ')[
												  -2])  # robust against different spellings of Naamstemming and Vote nominatif: just taking last word, # ignoring (annulé/geannuleerd) at the end of the line
						else:
							vote_number = int(page_line.rstrip().split(' ')[-1])
						logging.debug(f"Extracted vote number: #{vote_number}.")

					elif "Oui" in page_line and "Ja" in page_line:
						# Starting to process yes votes:
						logging.debug("Starting to process yes votes.")
						current_vote_type = VoteType.YES
						num_votes_yes = int(self.word_before("Ja", page_line))
						vote_names_lines = []

					elif "Non" in page_line and "Nee" in page_line:
						# Finishing processing of yes votes:
						logging.debug("Finishing processing of yes votes.")
						vote_names_yes = self.get_politician_names(vote_names_lines)
						# Starting to process no votes:
						logging.debug("Starting to process no votes.")
						current_vote_type = VoteType.NO
						num_votes_no = int(self.word_before("Nee", page_line))
						vote_names_lines = []

					elif "Abstentions" in page_line and "Onthoudingen" in page_line:
						# Finishing processing of no votes:
						logging.debug("Finishing processing of no votes.")
						vote_names_no = self.get_politician_names(vote_names_lines)
						# Starting to process abstention votes:
						logging.debug("Starting to process abstention votes.")
						current_vote_type = VoteType.ABSTENTION
						num_votes_abstention = int(self.word_before("Onthoudingen", page_line))
						vote_names_lines = []

					elif current_vote_type is not None and self.is_not_empty_line(page_line):
						# A new line of politician names for a yes/no/abstention vote to be added for later processing:
						vote_names_lines.append(page_line)
			else:
				# The current page does not contain votes by name anymore. Stop processing next pages.
				break

		return motions

	def word_before(self, word, page_line):
		return self.word_near(word, page_line, -1)

	def word_after(self, word, page_line):
		return self.word_near(word, page_line, +1)

	def word_near(self, word, page_line, words_distance):
		if ' ' in word:
			raise ValueError("Word cannot contain a space, given we split on spaces during finding of word.")
		words = page_line.split(' ')
		if word in words:
			return words[words.index(word) + words_distance]
		else:
			return None

	def get_politician_names(self, vote_name_lines):
		vote_names_text = "".join([line for line in vote_name_lines if self.is_not_empty_line(line)])
		vote_names = vote_names_text.split(", ")  # always last name, then first name in one word.
		vote_names = [name.strip() for name in vote_names]  # clean trailing spaces in names
		return vote_names

	def is_not_empty_line(self, page_line):
		return len(page_line.replace(' ', '')) > 0


class FederalChamberVotingHtmlExtractor:
	"""
	Extract voting behavior from a voting report on the Belgian federal chamber's website,
	for example at https://www.dekamer.be/kvvcr/showpage.cfm?section=/flwb/recent&language=nl&cfm=/site/wwwcfm/flwb/LastDocument.cfm.
	"""

	def extract_all(self, file_pattern, limit=None):
		report_names = glob.glob(file_pattern)
		report_names = report_names[:limit if limit is not None else len(report_names)]

		return dict([(report, self.extract(report)) for report in report_names])

	def extract(self, voting_report: str) -> List[Motion]:
		with open(voting_report, "r", encoding="cp1252") as file:
			html_content = file.read()

		soup = BeautifulSoup(html_content, "html.parser")
		text = soup.get_text()

		tokenized_text = TokenizedText(text)

		return self.extract_motions(voting_report, tokenized_text)

	def extract_motions(self, report, tokenized_text) -> list[Motion]:
		tokens = tokenized_text.tokens
		votings = find_occurrences(tokens, "Vote nominatif - Naamstemming:".split(" "))

		bounds = zip(votings, votings[1:] + [len(tokens)])
		voting_sequences = [tokens[start:end] for start, end in bounds]

		result = []

		for seq in voting_sequences:
			motion_nr = seq[4]
			ctx = MotionContext(report, int(motion_nr, 10))

			cancelled = sum([1 if "geannuleerd" in token else 0 for token in seq[4:8]]) > 0
			yes_start = get_sequence(seq, ["Oui"])
			no_start = get_sequence(seq, ["Non"])
			abstention_start = get_sequence(seq, ["Abstentions"])

			if not (yes_start < no_start < abstention_start):
				raise Exception("Could not parse voting sequence: %s", (" ".join(seq)))

			yes_count = int(seq[yes_start + 1], 10)
			no_count = int(seq[no_start + 1], 10)
			abstention_count = int(seq[abstention_start + 1], 10)

			yes_voters = self.get_names(ctx, seq[yes_start + 3: no_start], yes_count)
			no_voters = self.get_names(ctx, seq[no_start + 3:abstention_start], no_count)
			abstention_voters = self.get_names(ctx, seq[abstention_start + 3:], abstention_count)

			result.append(Motion(
								MotionId(report=report, nr=motion_nr),
								Proposal(0, "todo"),
								 num_votes_yes=yes_count,
								 vote_names_yes=yes_voters,
								 num_votes_no=no_count,
								 vote_names_no=no_voters,
								 num_votes_abstention=abstention_count,
								 vote_names_abstention=abstention_voters,
								 cancelled=cancelled,
								 parse_problems=ctx.problems))

		return result

	def get_names(self, ctx, sequence, count):
		names = [n.strip() for n in (" ".join(sequence).strip()).split(",") if n.strip() != '']

		if len(names) != count:
			ctx.problems.append("vote count (%d) does not match voters %s" % (count, str(names)))
			return None

		return names


class TokenizedText:

	def __init__(self, text):
		self.text = text
		self.tokens = WhitespaceTokenizer().tokenize(text)


def find_sequence(tokens, query, start_pos=0):
	"""@return index where the token sequence 'query' occurs in given tokens or -1 if the query sequence is not found"""
	if query[0] not in tokens:
		return -1
	pos = start_pos
	while query[0] in tokens[pos:]:
		next_pos = tokens.index(query[0], pos)
		if next_pos != -1:
			if tokens[next_pos:next_pos + len(query)] == query:
				return next_pos
		pos = next_pos + 1

	return -1


@dataclass
class MotionContext:
	report: str
	motion_nr: int
	problems: list[str] = field(default_factory=list)


def get_sequence(tokens, query):
	"""@return like find_sequence but raises ValueError if the query was not found"""
	pos = find_sequence(tokens, query)
	if pos >= 0:
		return pos
	raise ValueError("query %s not found in tokens %s" % (str(query), str(tokens)))


def find_occurrences(tokens, query):
	result = []
	pos = find_sequence(tokens, query)
	while pos > -1:
		result.append(pos)
		pos = find_sequence(tokens, query, pos + 1)

	return result


if __name__ == "__main__":
	voting_extractor = FederalChamberVotingPdfExtractor()

	# Inspect a page:
	voting_extractor.print_page("../data/input/pdf/ip298.pdf", 0)

	# Extract the interesting voting info:
	voting_extractor.extract("../data/input/pdf/ip298.pdf")
