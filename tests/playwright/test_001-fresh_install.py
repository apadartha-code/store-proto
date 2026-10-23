import re
from pathlib import Path

from playwright.sync_api import Page, expect

_SET_01_DIR = Path(__file__).resolve().parent.parent / "data" / "images" / "set-01"


def test_blank_db_latest(page: Page) -> None:
    page.goto("http://127.0.0.1:5000/")


def test_blank_db_landing(page: Page) -> None:
    page.goto("http://127.0.0.1:5000/")
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_test_id("mode-random").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_role("searchbox", name="Search names, tags, category").click()
    page.get_by_role("searchbox", name="Search names, tags, category").fill("abcd")
    page.get_by_test_id("search-submit").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_test_id("search-clear").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_test_id("settings-toggle").click()
    page.get_by_label("Category General Adult").select_option("all")
    page.get_by_label("Sharing Public and Shared").select_option("all")
    page.get_by_test_id("settings-apply").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_role("searchbox", name="Search names, tags, category").click()
    page.get_by_role("searchbox", name="Search names, tags, category").fill("abcd")
    page.get_by_role("searchbox", name="Search names, tags, category").press("Enter")
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_test_id("search-clear").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    
    page.get_by_test_id("mode-random").click()
    # @Cursor: Add assertion:
    # - There are no thumbnails visible.
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")

def test_blank_db_nickname_search(page: Page) -> None:
    page.goto("http://127.0.0.1:5000/")
    page.get_by_role("link", name="Find by nickname").click()
    page.get_by_role("textbox", name="Nickname (text or 6-char hex").click()
    page.get_by_role("textbox", name="Nickname (text or 6-char hex").fill("nickname")
    page.get_by_test_id("recall-find").click()
    expect(page.locator("section")).to_contain_text("No matching images in database")
    page.get_by_role("link", name="Image Store").click()
    expect(page.get_by_role("main")).to_contain_text("No images match this view. Try another search or adjust settings.")
    expect(page.get_by_role("main")).to_contain_text("1 / 1")

def test_blank_db_upload(page: Page) -> None:
    page.goto("http://127.0.0.1:5000/")
    page.get_by_test_id("upload-open").click()
    
    images = ["Caucasian Girl.jpg", "Cute Kid.jpg", "Falafel.jpg", "Pizza.jpg", "Pyramid of Giza.jpg", "Statue of Liberty.jpg", "Storm 05.jpg", "Storm 06.jpg", "Taj Mahal.jpg", "westerlund-2_42916480792_o.jpg", "Zhangjiajie Glass Bridge.jpg"]
    image_paths = [str(_SET_01_DIR / img) for img in images]
    
    page.get_by_role("button", name="Files").set_input_files(image_paths)
    page.get_by_label("Sharing Public Shared Private").select_option("shared")
    # page.get_by_label("License Private Unknown").click()
    page.get_by_test_id("upload-submit").click()
    expect(page.get_by_role("main")).to_contain_text("1 / 1")
    expect(page.get_by_role("link", name="westerlund-2_42916480792_o.")).to_be_visible()
    # @Cursor: Add assertion:
    # - Number of images displayed equals the count of uploaded image, or 60, whichever is lesser.

