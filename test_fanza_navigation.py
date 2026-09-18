import unittest
from unittest.mock import MagicMock, patch

import DojinRenamer as app


class ImmediateWait:
    """Run multiple polling steps without sleeping or launching Chrome."""
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, predicate):
        for _ in range(12):
            result = predicate(self.driver)
            if result:
                return result
        raise app.TimeoutException("not ready")


class FanzaNavigationTests(unittest.TestCase):
    def setUp(self):
        self.wait = patch.object(app, "WebDriverWait", ImmediateWait)
        self.wait.start()
        self.addCleanup(self.wait.stop)
        self.driver = MagicMock()
        self.driver.current_url = "https://www.fanza.jp/top/"
        self.driver.execute_script.return_value = "complete"
        self.driver.find_elements.return_value = []
        self.product = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_441050/"

    def test_expired_cookies_still_require_confirmation(self):
        driver = self.driver
        driver.current_url = "https://www.dmm.co.jp/age_check/"
        button = MagicMock()
        driver.find_elements.return_value = [button]
        def click():
            driver.current_url = "https://www.fanza.jp/top/"
            driver.find_elements.return_value = []
            driver.execute_script.side_effect = ["loading", "complete", "complete", "complete"]
        button.click.side_effect = click
        with patch.object(app, "load_cookies", return_value=True), patch.object(app, "save_cookies") as save:
            app.setup_fanza(driver)
        driver.refresh.assert_called_once()
        button.click.assert_called_once()
        save.assert_called_once_with(driver)
        self.assertEqual(driver.execute_script.call_count, 4)

    def test_confirmation_timeout_does_not_save_cookies(self):
        self.driver.current_url = "https://www.dmm.co.jp/age_check/"
        with patch.object(app, "save_cookies") as save, self.assertRaises(app.TimeoutException):
            app.confirm_fanza_age(self.driver)
        save.assert_not_called()

    def test_top_redirect_retries_same_product_once(self):
        title = MagicMock()
        title.text = "Title"
        title.get_attribute.return_value = "Circle"
        calls = []
        def navigate(url):
            calls.append(url)
            self.driver.current_url = "https://www.fanza.jp/top/" if len(calls) == 1 else url
        self.driver.get.side_effect = navigate
        self.driver.find_elements.side_effect = lambda by, selector: [] if by == app.By.XPATH else [title]
        app.open_fanza_product(self.driver, self.product)
        self.assertEqual(calls, [self.product, self.product])

    def test_persistent_redirect_stops_after_two_attempts(self):
        with self.assertRaises(RuntimeError):
            app.open_fanza_product(self.driver, self.product)
        self.assertEqual(self.driver.get.call_count, 2)

    def test_normal_product_is_not_retried(self):
        self.driver.current_url = self.product
        element = MagicMock()
        element.text = "Title"
        element.get_attribute.return_value = "Circle"
        self.driver.find_elements.side_effect = lambda by, selector: [] if by == app.By.XPATH else [element]
        app.open_fanza_product(self.driver, self.product)
        self.driver.get.assert_called_once_with(self.product)

    def test_product_age_redirect_is_confirmed_then_retried(self):
        button = MagicMock()
        element = MagicMock()
        element.text = "Title"
        element.get_attribute.return_value = "Circle"
        visits = []
        def navigate(url):
            visits.append(url)
            self.driver.current_url = "https://www.dmm.co.jp/age_check/" if len(visits) == 1 else url
        def find(by, selector):
            if by == app.By.XPATH:
                return [button] if "age_check" in self.driver.current_url else []
            return [element]
        button.click.side_effect = lambda: setattr(self.driver, "current_url", "https://www.fanza.jp/top/")
        self.driver.get.side_effect = navigate
        self.driver.find_elements.side_effect = find
        with patch.object(app, "save_cookies"):
            app.open_fanza_product(self.driver, self.product)
        self.assertEqual(visits, [self.product, self.product])
        button.click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
