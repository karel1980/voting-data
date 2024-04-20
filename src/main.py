import glob
import os
import logging
from bs4 import BeautifulSoup

from voting_serializers import MotionToMarkdownSerializer
from voting_extractors import FederalChamberVotingExtractor


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO) # or DEBUG to see debugging info as well.

INPUT_REPORTS_PATH = "../data/input"
OUTPUT_MARKDOWN_PATH = "../data/output"

def main():
    #convert_to_markdown()
    convert_to_json()

def convert_to_markdown():
    # Process all input reports:
    input_reports = glob.glob(os.path.join(INPUT_REPORTS_PATH, "*.pdf"))
    logging.debug(f"Will process the following input reports: {input_reports}.")
    
    for input_report in input_reports:
        try:
            # Extract the interesting voting info:
            logging.debug(f"Processing input report {input_report}...")
            voting_extractor = FederalChamberVotingExtractor()
            voting_serializer = MotionToMarkdownSerializer()
            # if input_report.endswith("ip298.pdf"):
            motions = voting_extractor.extract(input_report)
            _, output_markdown_file_name = os.path.split(input_report)
            plenary_number = int(output_markdown_file_name.split(".pdf")[0].replace("ip", ""))
            voting_serializer.serialize_motions(motions, plenary_number, os.path.join(OUTPUT_MARKDOWN_PATH, f"plenary {plenary_number}.md"))
        except Exception as e:
            logging.warning(e) # TODO rare errors to fix + in some pdfs, no motions could be extracted - to fix.

def convert_to_json():
    input_reports = glob.glob(os.path.join(INPUT_REPORTS_PATH, "*.html"))
    logging.debug(f"Processing {len(input_reports)} reports.")
    for report in input_reports:
        print("report",report)
        motions = voting_extractor.extract_html(input_report)

        JsonVotingSerializer().serialize(motions)

if __name__ == "__main__":
    main()
