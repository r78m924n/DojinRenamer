import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import DojinRenamer as app


class MetadataSafetyTests(unittest.TestCase):
    def run_main(self, driver):
        with ExitStack() as stack:
            stack.enter_context(patch.object(app.webdriver, "Chrome", return_value=driver))
            stack.enter_context(patch.object(app, "ChromeDriverManager"))
            stack.enter_context(patch.object(app, "Service"))
            stack.enter_context(patch.object(app.time, "sleep"))
            stack.enter_context(patch.object(app, "load_cookies", return_value=True))
            download = stack.enter_context(patch.object(app, "download_image"))
            stack.enter_context(patch("builtins.input", return_value=""))
            stack.enter_context(patch("builtins.print"))
            app.main()
            return download

    def test_failed_pages_preserve_names_and_move_queue_to_failures(self):
        for cid, page_url in (
            ("d_123456", "https://www.dmm.co.jp/age_check/"),
            ("RJ123456", "https://www.dlsite.com/maniax/work/=/product_id/RJ123456.html"),
            ("RJ123456", "https://www.dlsite.com/maniax/error/"),
        ):
            with self.subTest(cid=cid, page_url=page_url), tempfile.TemporaryDirectory() as tmp:
                with patch.object(app, "os", wraps=os) as mock_os:
                    targets = Path(tmp) / "targets"
                    targets.mkdir()
                    original_file = targets / f"Original {cid}.zip"
                    original_file.write_bytes(b"archive")
                    original_folder = targets / f"Original {cid}"
                    original_folder.mkdir()
                    (original_folder / "content.txt").write_bytes(b"content")
                    queue = targets / "url.txt"
                    queue.write_text(cid + "\n", encoding="utf-8")
                    # Resolve only the app's relative targets path into the temporary fixture.
                    mock_os.path = MagicMock(wraps=os.path)
                    mock_os.path.join.side_effect = lambda first, *rest: os.path.join(
                        str(targets) if first == "targets" else first, *rest
                    )
                    mock_os.makedirs.side_effect = lambda path, **kw: os.makedirs(
                        targets if path == "targets" else path, **kw
                    )
                    mock_os.listdir.side_effect = lambda path: os.listdir(
                        targets if path == "targets" else path
                    )
                    driver = MagicMock()
                    driver.current_url = page_url
                    driver.page_source = ""
                    driver.find_element.side_effect = LookupError("No product elements")
                    driver.find_elements.return_value = []
                    download = self.run_main(driver)
                    self.assertEqual(original_file.read_bytes(), b"archive")
                    self.assertEqual((original_folder / "content.txt").read_bytes(), b"content")
                    self.assertEqual(queue.read_text(encoding="utf-8"), "")
                    failures = app.load_failures(str(targets / "failed.csv"))
                    self.assertEqual(list(failures), [cid.upper()])
                    self.assertTrue(failures[cid.upper()]["reason"])
                    self.assertEqual(len(list(targets.iterdir())), 4)
                    download.assert_not_called()
                    driver.quit.assert_called_once()
                    driver.reset_mock()
                    self.run_main(driver)
                    driver.get.assert_not_called()
                    # Explicitly queueing the CID retries it without adding duplicate rows.
                    queue.write_text(cid + "\n", encoding="utf-8")
                    self.run_main(driver)
                    self.assertTrue(driver.get.called)
                    self.assertEqual(len(app.load_failures(str(targets / "failed.csv"))), 1)
                    # A failure to persist the error must leave the input queue intact.
                    queue.write_text(cid + "\n", encoding="utf-8")
                    with patch.object(app.os, "replace", side_effect=OSError("disk full")):
                        self.run_main(driver)
                    self.assertEqual(queue.read_text(encoding="utf-8"), cid + "\n")
                    self.assertEqual(app.load_failures(str(targets / "failed.csv")), failures)

    def test_required_fields_are_checked_after_name_cleanup(self):
        for data in (None, {}, {"title": "Title"}, {"circle": "Circle"},
                     {"circle": "\n", "title": "Title"},
                     {"circle": "Circle", "title": "Ver1.0"}):
            with self.subTest(data=data):
                self.assertFalse(app.has_required_metadata(data))

    def test_optional_fields_are_not_required(self):
        data = {"cid": "RJ123456", "circle": "Circle", "title": "Title"}
        self.assertTrue(app.has_required_metadata(data))
        self.assertEqual(app.build_base_name(data), "[Circle][RJ123456] Title")


if __name__ == "__main__":
    unittest.main()
