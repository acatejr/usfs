"""
USFS metadata download and catalog-build logic.

This module is the core of the Catalog tool.  It provides the ``USFS`` service
class, which handles:

1. **Downloading** raw metadata from three distinct USFS data sources:

   * **FSGeodata** — individual XML metadata files scraped from the USFS
     Geodata Clearinghouse at ``data.fs.usda.gov``.
   * **GDD (Geodata Discovery Database)** — a single DCAT-US 1.1 JSON feed
     published on the USFS ArcGIS Hub.
   * **RDA (Research Data Archive)** — a single JSON feed from the USFS
     Research Data Archive web service.

2. **Building** a unified catalog by parsing each downloaded source and
   normalising records into the common ``dict`` structure expected by
   ``schema.USFSDocument``, then writing the combined output to
   ``data/usfs/usfs_catalog.json``.

All downloaded files are written beneath ``./data/usfs/`` and are organised
by source sub-directory (``fsgeodata/``, ``gdd/``, ``rda/``).  Files that
already exist are skipped so that repeat runs are safe and incremental.
"""

import os
import requests
import json
from pathlib import Path
import click
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import string
from .lib import clean_str, hash_string


class USFS:
    """Service class for USFS metadata operations.

    Encapsulates all download and catalog-build logic for the three USFS
    metadata sources.  Each public method corresponds to one discrete step in
    the pipeline so that steps can be run individually or composed together via
    ``build_catalog``.

    Attributes:
        output_dir: Root directory for all downloaded files and output
            artifacts.  Defaults to ``./data/usfs`` relative to the working
            directory from which the CLI is invoked.
    """

    def __init__(self):
        self.output_dir = "./data/usfs"

    def download_fsgeodata_metadata(self):
        """Download XML metadata files from the USFS Geodata Clearinghouse.

        Scrapes the dataset listing page at ``data.fs.usda.gov/geodata/edw/datasets.php``
        to discover all datasets that have an associated XML metadata file.
        Each metadata file is then fetched individually and written to
        ``data/usfs/fsgeodata/<dataset_name>.xml``.

        Files that already exist on disk are skipped, making the method safe
        to call repeatedly without re-downloading unchanged data.

        Side effects:
            Creates ``data/usfs/fsgeodata/`` if it does not already exist.
            Writes one ``.xml`` file per discovered dataset.
            Prints progress messages via ``click.echo``.

        Raises:
            requests.exceptions.HTTPError: If the dataset listing page or any
                individual metadata request returns a non-2xx HTTP status.
        """
        BASE_URL = "https://data.fs.usda.gov"
        METADATA_BASE_URL = f"{BASE_URL}/geodata/edw/edw_resources/meta/"
        DATASETS_URL = f"{BASE_URL}/geodata/edw/datasets.php"

        output_dir = f"{self.output_dir}/fsgeodata"
        self.mkdir_output(output_dir)

        session = requests.Session()
        session.headers.update(
            {"User-Agent": "Mozilla/5.0 (compatible; FSGeodataDownloader/1.0)"}
        )
        response = session.get(DATASETS_URL)
        response.raise_for_status()
        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")
        datasets = []

        # Find all links to metadata XML files
        for link in soup.find_all("a", href=True):
            href = link["href"]

            # Look for metadata XML files
            if "/meta/" in href and href.endswith(".xml"):
                dataset_name = Path(href).stem
                metadata_url = urljoin(METADATA_BASE_URL, dataset_name + ".xml")

                # Try to find associated map service URL in nearby elements
                service_url = None
                parent = link.find_parent()
                if parent:
                    # Look for MapServer links in the same section
                    service_links = parent.find_all(
                        "a", href=lambda h: h and "MapServer" in h
                    )
                    if service_links:
                        service_url = service_links[0]["href"]

                datasets.append(
                    {
                        "name": dataset_name,
                        "metadata_url": metadata_url,
                        "service_url": service_url,
                    }
                )

        click.echo(f"Found {len(datasets)} datasets with metadata links.")
        for dataset in datasets:
            meta_path = Path(output_dir) / f"{dataset['name']}.xml"
            if not os.path.exists(meta_path):
                click.echo(f"   Downloading metadata for {dataset['name']}...")
                try:
                    meta_response = session.get(dataset["metadata_url"])
                    meta_response.raise_for_status()
                    meta_path = Path(output_dir) / f"{dataset['name']}.xml"
                    with open(meta_path, "w", encoding="utf-8") as f:
                        f.write(meta_response.text)

                except requests.exceptions.RequestException as e:
                    click.echo(
                        f"   Failed to download metadata for {dataset['name']}: {e}"
                    )
            else:
                click.echo(
                    f"   Metadata for {dataset['name']} already exists. Skipping."
                )

    def download_gdd_metadata(self):
        """Download the GDD metadata feed from the USFS ArcGIS Hub.

        Fetches the DCAT-US 1.1 JSON catalog published at the USFS ArcGIS Hub
        and writes it to ``data/usfs/gdd/gdd_metadata.json``.  The feed
        contains dataset-level metadata (title, description, keywords, themes,
        distribution links) for all datasets registered in the Geodata
        Discovery Database.

        If the destination file already exists the download is skipped.

        Side effects:
            Creates ``data/usfs/gdd/`` if it does not already exist.
            Writes ``gdd_metadata.json`` to that directory.
            Prints a skip or completion message via ``click.echo``.

        Raises:
            requests.exceptions.HTTPError: If the remote feed request returns
                a non-2xx HTTP status.
        """
        source_url = "https://data-usfs.hub.arcgis.com/api/feed/dcat-us/1.1.json"
        dest_output_dir = "./data/usfs/gdd"
        dest_output_file = "gdd_metadata.json"

        if os.path.exists(f"{dest_output_dir}/{dest_output_file}"):
            click.echo("   GDD metadata already exists. Skipping download.")
            return

        self.mkdir_output(dest_output_dir)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.fs.usda.gov/",
        }

        response = requests.get(source_url, headers=headers)
        response.raise_for_status()
        json_data = response.json()

        src_file = Path(dest_output_dir) / dest_output_file
        with open(src_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4)

    def download_rda_metadata(self):
        """Download the RDA metadata feed from the USFS Research Data Archive.

        Fetches the JSON catalog published by the USFS Research Data Archive
        web service and writes it to ``data/usfs/rda/rda_metadata.json``.  The
        feed contains dataset-level metadata (title, description, keywords,
        identifiers, distribution links) for all datasets registered in the
        RDA.

        If the destination file already exists the download is skipped.

        Side effects:
            Creates ``data/usfs/rda/`` if it does not already exist.
            Writes ``rda_metadata.json`` to that directory.
            Prints a skip or completion message via ``click.echo``.

        Raises:
            requests.exceptions.HTTPError: If the remote feed request returns
                a non-2xx HTTP status.
        """

        source_url = "https://www.fs.usda.gov/rds/archive/webservice/datagov"
        dest_output_dir = "./data/usfs/rda"
        dest_output_file = "rda_metadata.json"

        if os.path.exists(f"{dest_output_dir}/{dest_output_file}"):
            click.echo("   RDA metadata already exists. Skipping download.")
            return

        self.mkdir_output(dest_output_dir)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.fs.usda.gov/",
        }
        response = requests.get(source_url, headers=headers)
        response.raise_for_status()
        json_data = response.json()

        src_file = Path(dest_output_dir) / dest_output_file
        with open(src_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4)

    def mkdir_output(self, dir_path: str = None) -> None:
        """Create a directory, including any missing parent directories.

        A thin wrapper around ``os.makedirs(..., exist_ok=True)`` used by the
        download methods to ensure destination directories are present before
        writing files.

        Args:
            dir_path: Path to the directory to create.  Defaults to
                ``self.output_dir`` (``./data/usfs``) when omitted.
        """

        if dir_path is None:
            dir_path = self.output_dir

        os.makedirs(dir_path, exist_ok=True)

    def build_gdd_catalog(self):
        """Parse the GDD metadata feed and return a list of document dicts.

        Reads ``data/usfs/gdd/gdd_metadata.json`` (written by
        ``download_gdd_metadata``), iterates over every entry in the
        ``dataset`` array, and normalises each entry into the common document
        structure used by ``schema.USFSDocument``.

        Fields extracted per record:

        * ``title`` — cleaned dataset title.
        * ``description`` — cleaned narrative description.
        * ``keyword`` — list of subject keywords.
        * ``theme`` — list of thematic category strings.

        The ``id`` field is derived by hashing the lower-cased, stripped title
        via ``lib.hash_string``.

        Returns:
            A list of dicts, each representing one GDD dataset record with keys
            ``id``, ``title``, ``description``, ``keywords``, ``themes``, and
            ``src`` (always ``"gdd"``).  Returns an empty list if the metadata
            file does not exist.

        Side effects:
            Prints a "not found" or "processing" message via ``click.echo``.
        """
        documents = []

        gdd_json_path = f"{self.output_dir}/gdd/gdd_metadata.json"
        if not os.path.exists(gdd_json_path):
            click.echo("\tGDD metadata not found.")
        else:
            with open(gdd_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

                if "dataset" in json_data.keys():
                    dataset = json_data.get("dataset")

                    if dataset and len(dataset) > 0:
                        for item in dataset:
                            title = (
                                clean_str(item.get("title"))
                                if "title" in item.keys()
                                else ""
                            )
                            description = (
                                clean_str(item.get("description"))
                                if "description" in item.keys()
                                else ""
                            )
                            keyword = (
                                item.get("keyword") if "keyword" in item.keys() else []
                            )
                            kw = self.clean_keywords(keyword)
                            theme = item.get("theme") if "theme" in item.keys() else []

                            document = {
                                "id": hash_string(title.lower().strip()),
                                "title": title,
                                "description": description,
                                "keywords": kw,
                                "themes": theme,
                                "src": "gdd",
                            }

                            documents.append(document)

        return documents

    def build_rda_catalog(self):
        """Parse the RDA metadata feed and return a list of document dicts.

        Reads ``data/usfs/rda/rda_metadata.json`` (written by
        ``download_rda_metadata``), iterates over every entry in the
        ``dataset`` array, and normalises each entry into the common document
        structure used by ``schema.USFSDocument``.

        Fields extracted per record:

        * ``title`` — cleaned dataset title.
        * ``description`` — cleaned narrative description.
        * ``keyword`` — list of subject keywords.

        The RDA feed does not include a ``theme`` field; ``themes`` is always
        set to an empty list.  The ``id`` field is derived by hashing the
        lower-cased, stripped title via ``lib.hash_string``.

        Returns:
            A list of dicts, each representing one RDA dataset record with keys
            ``id``, ``title``, ``description``, ``keywords``, ``themes``, and
            ``src`` (always ``"rda"``).  Returns an empty list if the metadata
            file does not exist.

        Side effects:
            Prints a "not found" or "processing" message via ``click.echo``.
        """
        documents = []

        rda_json_path = f"{self.output_dir}/rda/rda_metadata.json"
        if not os.path.exists(rda_json_path):
            click.echo("\tRDA metadata not found.")
        else:
            with open(rda_json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

                if "dataset" in json_data.keys():
                    dataset = json_data.get("dataset")

                    if dataset and len(dataset) > 0:
                        for item in dataset:
                            title = (
                                clean_str(item.get("title"))
                                if "title" in item.keys()
                                else ""
                            )
                            description = (
                                clean_str(item.get("description"))
                                if "description" in item.keys()
                                else ""
                            )
                            keyword = (
                                item.get("keyword") if "keyword" in item.keys() else []
                            )
                            kw = self.clean_keywords(keyword)
                            document = {
                                "id": hash_string(title.lower().strip()),
                                "title": title,
                                "description": description,
                                "keywords": kw,
                                "themes": [],
                                "src": "rda",
                            }

                            documents.append(document)

        return documents

    def clean_keywords(self, keywords: list[str]) -> list[str]:
        cleaned = []
        for kw in keywords:
            kw = kw.strip().lower().translate(str.maketrans("", "", string.punctuation))
            if kw:
                cleaned.append(kw)
        return list(dict.fromkeys(cleaned))  # deduplicate, preserve order

    def build_fsgeodata_catalog(self):
        """Parse FSGeodata XML metadata files and return a list of document dicts.

        Scans ``data/usfs/fsgeodata/`` for every ``.xml`` file written by
        ``download_fsgeodata_metadata`` and parses each one with BeautifulSoup.
        The following FGDC-standard XML elements are extracted:

        * ``<title>`` — dataset title (top-level element).
        * ``<descript>/<abstract>`` — executive summary of the dataset.
        * ``<descript>/<purpose>`` — statement of why the dataset was created.
        * ``<dataqual>/<procstep>`` elements — data-quality lineage steps, each
          captured as a dict with ``"description"`` and ``"date"`` keys.
        * ``<themekey>`` elements — controlled-vocabulary theme keywords.

        The ``id`` field is derived by hashing the lower-cased, stripped title
        via ``lib.hash_string``.

        Returns:
            A list of dicts, each representing one FSGeodata dataset with keys
            ``id``, ``title``, ``abstract``, ``purpose``, ``keywords``,
            ``lineage``, and ``src`` (always ``"fsgeodata"``).

        Side effects:
            Reads XML files from ``data/usfs/fsgeodata/``.
        """
        documents = []
        xml_path = f"{self.output_dir}/fsgeodata"
        xml_files = Path(xml_path)

        if xml_files.is_dir():
            xml_files = list(xml_files.glob("*.xml"))
        else:
            xml_files = [xml_files]

        for idx, xml_file in enumerate(xml_files):
            with open(xml_file, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "xml")
                abstract = ""
                purpose = ""
                keywords = []
                procdate = ""
                procdesc = ""

                title_elem = soup.find("title")
                title = clean_str(title_elem.get_text()) if title_elem else ""

                descript = soup.find("descript")
                if descript:
                    abstract_elem = descript.find("abstract")
                    abstract = (
                        clean_str(abstract_elem.get_text()) if abstract_elem else ""
                    )
                    purpose_elem = descript.find("purpose")
                    purpose = clean_str(purpose_elem.get_text()) if purpose_elem else ""

                lineage = []
                dataqual = soup.find_all("dataqual")
                if dataqual:
                    dq = dataqual[0]
                    procsteps = dq.find_all("procstep")
                    for step in procsteps:
                        if step.find("procdate"):
                            procdate = step.find("procdate").get_text()
                        if step.find("procdesc"):
                            procdesc = step.find("procdesc").get_text()

                        if procdate and procdesc:
                            procstep = {
                                "description": procdesc,
                                "date": procdate,
                            }
                            lineage.append(procstep)

                if soup.find_all("themekey") is not None:
                    themekeys = soup.find_all("themekey")
                    if len(themekeys) > 0:
                        keywords = self.clean_keywords(
                            [w.get_text() for w in themekeys]
                        )

                document = {
                    "id": hash_string(title.lower().strip()),
                    "title": title,
                    "lineage": lineage,
                    "abstract": abstract,
                    "purpose": purpose,
                    "keywords": keywords,
                    "src": "fsgeodata",
                }

                documents.append(document)

        return documents

    def build_catalog(self):
        """Build and persist the unified USFS metadata catalog.

        Orchestrates the three catalog-build methods in sequence:

        1. ``build_fsgeodata_catalog`` — parses FSGeodata XML files.
        2. ``build_gdd_catalog`` — parses the GDD JSON feed.
        3. ``build_rda_catalog`` — parses the RDA JSON feed.

        All resulting document dicts are combined into a single list and
        serialised as pretty-printed JSON to
        ``data/usfs/usfs_catalog.json``.  This file is the final artifact
        consumed by downstream search and AI retrieval tools.

        The method assumes that the relevant metadata files have already been
        downloaded by the corresponding ``download_*`` methods.  Missing
        source files are handled gracefully by the individual build methods
        (they return empty lists and print a warning).

        Side effects:
            Reads from ``data/usfs/fsgeodata/``, ``data/usfs/gdd/``, and
            ``data/usfs/rda/``.
            Writes ``data/usfs/usfs_catalog.json``.
        """
        documents = []

        # FSGeodata
        fsgeodata_documents = self.build_fsgeodata_catalog()
        documents.extend(fsgeodata_documents)

        # GDD
        gdd_documents = self.build_gdd_catalog()
        documents.extend(gdd_documents)

        # RDA
        rda_documents = self.build_rda_catalog()
        documents.extend(rda_documents)

        output_file = f"{self.output_dir}/usfs_catalog.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=4)
