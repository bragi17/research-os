"""Tests for the GROBID TEI parser."""

from services.parser.grobid_client import GROBIDClient


def test_parse_tei_xml_rejects_dtd_entity_payload_safely():
    tei_xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE TEI [
  <!ENTITY injected "EXPANDED_ENTITY_CONTENT">
]>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>&injected;</title>
      </titleStmt>
    </fileDesc>
  </teiHeader>
</TEI>
"""

    paper = GROBIDClient()._parse_tei_xml(tei_xml)

    assert paper.parse_quality == "low"
    assert paper.error_message is not None
    assert paper.title != "EXPANDED_ENTITY_CONTENT"


def test_parse_tei_xml_extracts_title_and_authors():
    tei_xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>Reliable Research Systems</title>
        <author>
          <persName>
            <forename>Ada</forename>
            <surname>Lovelace</surname>
          </persName>
        </author>
        <author>
          <persName>
            <forename>Grace</forename>
            <surname>Hopper</surname>
          </persName>
        </author>
      </titleStmt>
    </fileDesc>
  </teiHeader>
</TEI>
"""

    paper = GROBIDClient()._parse_tei_xml(tei_xml)

    assert paper.error_message is None
    assert paper.parse_quality == "high"
    assert paper.title == "Reliable Research Systems"
    assert paper.authors == [
        {"first_name": "Ada", "last_name": "Lovelace"},
        {"first_name": "Grace", "last_name": "Hopper"},
    ]
