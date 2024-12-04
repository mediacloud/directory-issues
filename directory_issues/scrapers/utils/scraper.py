import argparse
import logging
from time import sleep
import cloudscraper
from cloudscraper import CloudScraper

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(name)s | %(levelname)s: %(message)s")

class BaseScraper:
    def __init__(self):
        self.args = None
        self.data_to_scrape = ""
        self.max_retries = 3
        self.crawl_delay = 10
        self.scraper: CloudScraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows"})

    def scrape_content_with_retry(self, method, *args, **kwargs):
        """
        A method to for scraping content with exponential backoff.

        Args:
            method (callable): The method to execute.
            *args: Positional arguments for the method.
            **kwargs: Keyword arguments for the method.

        Returns:
            Any: The return value of the method, or None if retries fail.
        """
        number_of_retries = 0
        while number_of_retries < self.max_retries:
            try:
                result = method(*args, **kwargs)
                if result:
                    return result
            except Exception as e:
                logging.info(f"Error during execution: {e}")
            number_of_retries += 1
            delay = self.crawl_delay * number_of_retries
            logging.info("Retry [%s/%s]. Waiting %s seconds...", number_of_retries, self.crawl_delay, delay)
            sleep(delay)
        logging.error("Max retries reached. Method execution failed.")
        return None

    def define_options(self, ap):
        ap.add_argument(
            '--max-retries',
            type=int,
            dest="max_retries",
            default=3,
            help='Maximum number of retry attempts (default: 3)'
        )
        ap.add_argument(
            '--crawl-delay',
            type=int,
            dest="crawl_delay",
            default=1,
            help='Delay in seconds between retries (default: 10)'
        )
        ap.add_argument(
            '--data',
            type=str,
            dest="data",
            help='The type of data to scrape'
        )

    def process_args(self) -> None:
        assert self.args
        args = self.args
        self.crawl_delay = args.crawl_delay
        self.max_retries = args.max_retries
        self.data_to_scrape = args.data

    def main(self):
        ap = argparse.ArgumentParser()
        self.define_options(ap)
        self.args = ap.parse_args()  # This line was missing
        self.process_args()

