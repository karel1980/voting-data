import logging
import os
import unittest

import sys

from src.model import ParseProblem
from voting_extractors import FederalChamberVotingPdfExtractor, FederalChamberVotingHtmlExtractor, TokenizedText, \
	find_sequence, find_occurrences

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


class TestFederalChamberVotingPdfExtractor(unittest.TestCase):

	def test_extract(self):
		actual = FederalChamberVotingPdfExtractor().extract('../data/input/pdf/ip298.pdf')

		self.assertEqual(13, len(actual))

		self.assertEqual(10, actual[0].proposal.number)
		expected_description = 'Motions déposées en conclusion des  interpellations de'
		self.assertEqual(expected_description, actual[0].proposal.description[:len(expected_description)])

		self.assertEqual(16, actual[0].num_votes_yes)
		self.assertEqual(16, len(actual[0].vote_names_yes))
		self.assertEqual(['Bury Katleen', 'Creyelman Steven'], actual[0].vote_names_yes[:2])

		self.assertEqual(116, actual[0].num_votes_no, )
		self.assertEqual(116, len(actual[0].vote_names_no))
		self.assertEqual(["Anseeuw Björn", "Aouasti Khalil"], actual[0].vote_names_no[:2])

		self.assertEqual(1, actual[0].num_votes_abstention)
		self.assertEqual(1, len(actual[0].vote_names_abstention))
		self.assertEqual(['Özen Özlem'], actual[0].vote_names_abstention)

		self.assertEqual(False, actual[0].cancelled)


class TestFederalChamberVotingHtmlExtractor(unittest.TestCase):

	@unittest.skipIf(os.environ.get("SKIP_SLOW", None) is not None, "skipping slow tests")
	def test_extract_all_does_not_throw(self):
		actual = FederalChamberVotingHtmlExtractor().extract_all('../data/input/html/*.html')

		self.assertEqual(len(actual), 300)

		all_motions = [motion for motions in actual.values() for motion in motions]
		self.assertEqual(len(all_motions), 2842)

		motions_with_problems = list(filter(lambda m: len(m.parse_problems) > 0, all_motions))

		# TODO: Improve how we handle parsing problems
		self.assertEqual(len(motions_with_problems), 17)

	def test_extract_ip67(self):
		actual = FederalChamberVotingHtmlExtractor().extract('../data/input/html/ip067x.html')

		self.assertEqual(len(actual), 18)
		self.assertEqual(actual[0].parse_problems,
						 ["vote count (51) does not match voters []"])

	def test_extract_ip298(self):
		actual = FederalChamberVotingHtmlExtractor().extract('../data/input/html/ip298x.html')

		self.assertEqual(28, len(actual))
		# self.assertEqual(10, actual[0].proposal.number)
		# expected_description = 'Motions déposées en conclusion'
		# self.assertEqual(expected_description, actual[0].proposal.description[:len(expected_description)])
		motion0 = actual[0]

		self.assertEqual(79, motion0.num_votes_yes)
		self.assertEqual(79, len(motion0.vote_names_yes))
		self.assertEqual(['Aouasti Khalil', 'Bacquelaine Daniel'], motion0.vote_names_yes[:2])

		self.assertEqual(50, motion0.num_votes_no, )
		self.assertEqual(50, len(motion0.vote_names_no))
		self.assertEqual(["Anseeuw Björn", "Bruyère Robin"], motion0.vote_names_no[:2])

		self.assertEqual(4, motion0.num_votes_abstention)
		self.assertEqual(4, len(motion0.vote_names_abstention))
		self.assertEqual(['Arens Josy', 'Daems Greet'], motion0.vote_names_abstention[:2])

		self.assertEqual(False, motion0.cancelled)
		self.assertEqual(True, actual[11].cancelled)


class TestTokenizedText(unittest.TestCase):

	def test_find_sequence(self):
		text = "TO BE OR NOT TO BE"

		tokens = TokenizedText(text).tokens

		self.assertEqual(find_sequence(tokens, ["BALLOON"]), -1)
		self.assertEqual(find_sequence(tokens, ["TO"]), 0)
		self.assertEqual(find_sequence(tokens, ["OR"]), 2)
		self.assertEqual(find_sequence(tokens, ["NOT"]), 3)

		self.assertEqual(find_sequence(tokens, ["TO", "BE"]), 0)

	def test_find_occurrences(self):
		text = "TO BE OR NOT TO BE"

		tokens = TokenizedText(text).tokens

		self.assertEqual(find_occurrences(tokens, ["BALLOON"]), [])
		self.assertEqual(find_occurrences(tokens, ["TO", "BE"]), [0, 4])
		self.assertEqual(find_occurrences(tokens, ["TO", "OR"]), [])
		self.assertEqual(find_occurrences(tokens, ["BE", "FOO"]), [])
