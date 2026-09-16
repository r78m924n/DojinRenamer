import os
import tempfile
import unittest
from contextlib import ExitStack, chdir
from pathlib import Path
from unittest.mock import MagicMock, patch

import DojinRenamer as app


class MetadataSafetyTests(unittest.TestCase):
    def test_results_are_saved_before_browser_shutdown_failure(self):
        for success in (False, True):
            with self.subTest(success=success), tempfile.TemporaryDirectory() as tmp, chdir(tmp):
                targets = Path("targets")
                targets.mkdir()
                queue = targets / "url.txt"
                queue.write_text("d_123456\n", encoding="utf-8")
                driver = MagicMock()
                data = {"cid": "d_123456", "circle": "Circle", "title": "Title"}
                saved_at_quit = {}

                def broken_quit():
                    saved_at_quit["queue"] = queue.read_text(encoding="utf-8")
                    saved_at_quit["failures"] = app.load_failures("targets/failed.csv")
                    saved_at_quit["folder"] = (targets / "[Circle][d_123456] Title").is_dir()
                    raise ConnectionResetError("driver disconnected during quit")

                driver.quit.side_effect = broken_quit
                with patch.object(app, "get_metadata", return_value=data,
                                  side_effect=None if success else ConnectionResetError("driver disconnected")):
                    self.run_main(driver)
                driver.quit.assert_called_once()
                driver.set_page_load_timeout.assert_called_once_with(30)
                self.assertEqual(saved_at_quit["queue"], "")
                if success:
                    self.assertEqual(saved_at_quit["failures"], {})
                    self.assertTrue(saved_at_quit["folder"])
                else:
                    self.assertIn("ConnectionResetError", saved_at_quit["failures"]["D_123456"]["reason"])

    def test_navigation_logs_destination_and_propagates_errors(self):
        driver = MagicMock()
        driver.current_url = "https://example.test/redirected"
        with patch("builtins.print") as output:
            app.open_product_page(driver, "https://example.test/product")
        messages = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("https://example.test/product", messages)
        self.assertIn("https://example.test/redirected", messages)
        driver.get.side_effect = TimeoutError("page load timed out")
        with patch("builtins.print") as output, self.assertRaises(TimeoutError):
            app.open_product_page(driver, "https://example.test/product")
        self.assertEqual(output.call_count, 1)

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
