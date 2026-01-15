import unittest

import scripts.check_citations as check_citations


class CitationChecksTest(unittest.TestCase):
    def test_citation_enforcement(self) -> None:
        self.assertEqual(check_citations.main(), 0)


if __name__ == "__main__":
    unittest.main()
