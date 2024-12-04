import json
import logging
import os
from time import sleep
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Comment

from utils.scraper import BaseScraper
from utils.database import SQLiteMixin

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(name)s | %(levelname)s: %(message)s")

URLs = {
    "BASE_URL": "https://www.thepaperboy.com/",
    "COUNTRY_LIST": "/newspapers-by-country.cfm",
    "US_STATES_LIST": "/usa-newspapers-by-state.cfm"
}


DATABASE_PATH = "output/database/thepaperboy.db"
JSON_DUMP_PATH = "output/files"

class ThePaperBoyScraper(SQLiteMixin, BaseScraper):
    def __init__(self):
        super().__init__()
        self.db = None
        self.base_url: str = URLs.get("BASE_URL")
        self.DATABASE_PATH = DATABASE_PATH
        self.initialize_database()
        logger.info("Scraper is initialized with base URL %s", self.base_url)

    def initialize_database(self):
        self.db = self._get_connection()
        self.create_table('countries', {
            'id': 'INTEGER PRIMARY KEY',
            'name': 'TEXT NOT NULL',
            'url': 'TEXT NOT NULL UNIQUE',
            'crawl_status': 'TEXT CHECK (crawl_status IN ("pending", "in_progress", "completed")) DEFAULT "pending"',
            'start_crawl_time': 'TIMESTAMP DEFAULT NULL',
            'finish_crawl_time': 'TIMESTAMP DEFAULT NULL',
            'total': 'INTEGER DEFAULT NULL'
        })

        self.create_table('states', {
            'id': 'INTEGER PRIMARY KEY',
            'name': 'TEXT NOT NULL',
            'abbreviation': 'TEXT NOT NULL',
            'url': 'TEXT NOT NULL UNIQUE',
            'crawl_status': 'TEXT CHECK (crawl_status IN ("pending", "in_progress", "completed")) DEFAULT "pending"',
            'start_crawl_time': 'TIMESTAMP DEFAULT NULL',
            'finish_crawl_time': 'TIMESTAMP DEFAULT NULL',
            'total': 'INTEGER DEFAULT NULL'
        })

        self.create_table('sources', {
            'id': 'INTEGER PRIMARY KEY',
            'url': 'TEXT NOT NULL UNIQUE',
            'data': 'TEXT NOT NULL UNIQUE',
            'crawl_status': 'TEXT CHECK (crawl_status IN ("pending", "in_progress", "completed")) DEFAULT "pending"',
            'start_crawl_time': 'TIMESTAMP DEFAULT NULL',
            'finish_crawl_time': 'TIMESTAMP DEFAULT NULL'
        })

    def __scrape_locations(self, level):
        if level == "states":
            url = URLs.get("US_STATES_LIST")
            entry_point = "START MAIN LEFT COLUMN TABLE"
        else:
            url = URLs.get("COUNTRY_LIST")
            entry_point = "START MAIN COLUMN TABLE"

        total_records = self.count(level)

        if total_records == 0:
            data = []
            response = self.scraper.get(urljoin(self.base_url, url))
            soup = BeautifulSoup(response.text, features="lxml")
            comments = soup.find_all(string=lambda node: isinstance(node, Comment))
            for comment in comments:
                if entry_point in comment:
                    main_table = comment.find_next()
                    tables = main_table.find_all("table")
                    for table in tables:
                        rows = table.find_all("tr")
                        for row in rows:
                            anchors = row.find_all("a")
                            for anchor in anchors:
                                href = anchor.get("href")
                                text = anchor.get_text(strip=True)
                                if text != "(FP)":
                                    if level == "countries":
                                        location, total = self.extract_location_totals(text, level)
                                        if location and total:
                                            logger.info("Found: href=%s, location=%s, total=%s",
                                                        href, location, total)
                                            data.append({
                                                "name": location,
                                                "url": href,
                                                "total": total
                                            })
                                    elif level == "states":
                                        location, abbreviation, total = self.extract_location_totals(text, level)
                                        data.append({
                                            "name": location,
                                            "abbreviation": abbreviation,
                                            "url": href,
                                            "total": total
                                        })
                    break
            logger.info("Recording [%s] %s", len(data), level)
            self.bulk_insert(level, data, "IGNORE")
        else:
            logger.info("%s already set in database, no further processing is required", level)

        return True

    def __scrape_sources_from_specific_location(self, data):
        response = self.scraper.get(urljoin(self.base_url, data.get("url")))
        fetched_data = []
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, features="lxml")
            comments = soup.find_all(string=lambda text: isinstance(text, Comment))
            for comment in comments:
                if "START MAIN PAPER DISPLAY TABLE" in comment:
                    main_table = comment.find_next()
                    if data.get("country") == "United States":
                        no_columns = 3
                    else:
                        no_columns = 4
                    rows = main_table.find_all("tr")[1:]
                    for index, row in enumerate(rows, start=1):
                        cells = row.find_all("td")
                        if len(cells) == no_columns:
                            source_link_tag = cells[0].find("a")
                            name = source_link_tag.get_text(strip=True)
                            url = source_link_tag['href']

                            # Local sources (USA) have 3 columns, other sources have 4 columns
                            if no_columns == 4:
                                city = cells[1].find("a", href=True).get_text()
                                state = cells[2].find("a", href=True).get_text()
                                language = cells[3].find("font", class_="smallfont").get_text()
                                country = data.get("name")
                            else:
                                state = data.get("name")
                                city = cells[1].find("a", href=True).get_text()
                                language = cells[2].find("font", class_="smallfont").get_text()
                                country = data.get("country")

                            fetched_data.append({"url": url, "data": json.dumps({
                                "state": state,
                                "country": country,
                                "url": url,
                                "city": city,
                                "language": language,
                                "name": name
                            })})

            logger.info("Recording [%s] sources", len(fetched_data))
            self.bulk_insert("sources", fetched_data, "IGNORE")
            return fetched_data

    def __scrape_source_metadata(self, data):
        if data.get("url"):
            response = self.scraper.get(urljoin(self.base_url, data.get("url")))
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, features="lxml")
                # Get the link to the actual source website
                source_final_link = soup.find("h1").find("a")
                if source_final_link:
                    data["url"] = source_final_link.get('href')

                # Get the description of the source (this is mostly present for USA sources)
                pre_formatted_text = soup.find("pre")
                if pre_formatted_text:
                    data["description"] = pre_formatted_text.text.strip()

                # Get social details
                comments = soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments:
                    if "SHOW SOCIAL ICONS AVAILABLE" in comment:
                        data["social_media"] = []
                        social_tags_container = comment.find_next()
                        if social_tags_container:
                            social_tags = social_tags_container.find_all('a', target="_blank")
                            for social_tag in social_tags:
                                data["social_media"].append(self.extract_social_media_tag_info(social_tag))
                        break
        return data

    def scrape_us_sources(self):
        states = self.select("states", where="finish_crawl_time IS NULL")
        if len(states) > 0:
            for location in states:
                self.update("states", {"start_crawl_time": "CURRENT_TIMESTAMP",
                                          "crawl_status": "in_progress"}, "id = ?",
                            (location.get("id"),))
                logging.info("Starting to scrape sources from: %s", location.get("name"))
                location["level"] = "state"
                location["country"] = "United States"
                if self.scrape_sources_from_specific_location(location):
                    logger.info("Completed scraping sources from %s",location.get("name"))
                self.update("states", {"finish_crawl_time": "CURRENT_TIMESTAMP",
                                          "crawl_status": "completed"}, "id = ?",
                            (location.get("id"),))
                logging.info("Crawl delay. Waiting for %s seconds...", self.crawl_delay)
                sleep(self.crawl_delay)
        else:
            logger.info("Sources for all states have been to be scraped, exiting...")

    def scrape_non_us_sources(self):
        countries = self.select("countries",
                                where="finish_crawl_time IS NULL AND name <> ?",
                                params=("United States",)
                                )
        if len(countries) > 0:
            for location in countries:
                self.update("countries", {"start_crawl_time": "CURRENT_TIMESTAMP",
                                          "crawl_status": "in_progress"}, "id = ?",
                            (location.get("id"),))
                logging.info("Starting to scrape sources from: %s", location.get("name"))
                location["level"] = "country"
                if self.scrape_sources_from_specific_location(location):
                    logger.info("Completed scraping sources from %s",location.get("name"))
                self.update("countries", {"finish_crawl_time": "CURRENT_TIMESTAMP",
                                          "crawl_status": "completed"}, "id = ?",
                            (location.get("id"),))
                logging.info("Crawl delay. Waiting for %s seconds...", self.crawl_delay)
                sleep(self.crawl_delay)
        else:
            logger.info("Sources for all countries have been to be scraped, exiting...")

    def scrape_sources_metadata(self, location_type):
        if location_type == "local":
            locations = self.select("states")
        else:
            locations = self.select("countries",
                                    where="name <> ?",
                                    params=("United States",)
                                    )
        updated_data = None
        if len(locations) > 0:
            for location in locations:
                logger.info("Scraping sources from %s",location.get("name"))
                sources = self.select("sources", where="data LIKE ? AND finish_crawl_time IS NULL",
                                      params = (f"%{location.get('name')}%",))
                for source in sources:
                    data = json.loads(source.get("data"))
                    self.update("sources", {"start_crawl_time": "CURRENT_TIMESTAMP",
                                            "crawl_status": "in_progress"}, "id = ?",
                                (source.get("id"),))
                    updated_data = self.scrape_source_metadata_with_retry(data)
                    if updated_data:
                        logger.info("Recorded metadata for %s", data.get("name"))
                        self.update("sources", {"finish_crawl_time": "CURRENT_TIMESTAMP",
                                                "crawl_status": "completed", "data": json.dumps(updated_data)}, "id = ?",
                                    (source.get("id"),))
                    else:
                        logger.error("Unable to fetch metadata for %s", data.get("name"))
                        break

                    logging.info("Crawl delay. Waiting for %s seconds...", self.crawl_delay)
                    sleep(self.crawl_delay)

                if len(sources) > 0:
                    if not updated_data:
                        logging.error("Last fetch failed despite retrires, possible network problem exiting loop...")
                        break
                else:
                    logging.info("No pending sources found...")

        else:
            logger.info("No countries found, exiting...")

    def scrape_source_metadata_with_retry(self, data):
        return self.scrape_content_with_retry(self.__scrape_source_metadata, data)

    def scrape_sources_from_specific_location(self, data):
        return self.scrape_content_with_retry(self.__scrape_sources_from_specific_location, data)

    def scrape_countries(self):
        return self.scrape_content_with_retry(self.__scrape_locations, "countries")

    def scrape_states(self):
        return self.scrape_content_with_retry(self.__scrape_locations, "states")

    def export_sources_to_file(self):
        sources = self.select("sources",
                                where="crawl_status = ?",
                                params=("completed",)
                                )
        data = []
        for source in sources:
            data.append(json.loads(source.get("data")))

        os.makedirs(JSON_DUMP_PATH, exist_ok=True)

        # Write data to JSON file
        with open(f"{JSON_DUMP_PATH}/the_paperboy_sources.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        logger.info("Data has been written to file")

    @staticmethod
    def extract_location_totals(text: str, location_type: str):
        if location_type == "countries":
            pattern = r"(.*?)\s*\((\d+)\)"
            match = re.search(pattern, text)
            if match:
                country = match.group(1).strip()
                total = int(match.group(2))
                return country, total
        elif location_type == "states":
            pattern = r"(.*?)\[(.*?)\]\((\d+)\)"
            match = re.search(pattern, text)
            if match:
                state_name = match.group(1).strip()
                state_abbrev = match.group(2)
                total = int(match.group(3))
                return state_name, state_abbrev, total
        return None, None

    @staticmethod
    def extract_social_media_tag_info(social_media_anchor_tag):
        social_media_info = {}
        url = social_media_anchor_tag.get("href")
        if "wikipedia" in url:
            social_media_info["Wikipedia"] = url
        elif "facebook" in url:
            social_media_info["Facebook"] = url
        elif "twitter" in url:
            social_media_info["Twitter"] = url
        return social_media_info

    def main(self):
        super().main()
        if self.data_to_scrape == "countries":
            self.scrape_countries()
        elif self.data_to_scrape == "states":
            self.scrape_states()
        elif self.data_to_scrape == "non_us_sources":
            self.scrape_non_us_sources()
            self.scrape_sources_metadata("countries")
        elif self.data_to_scrape == "us_sources":
            self.scrape_us_sources()
            self.scrape_sources_metadata("local")
        elif self.data_to_scrape == "export":
            self.export_sources_to_file()


if __name__ == "__main__":
    scraper = ThePaperBoyScraper()
    scraper.main()
