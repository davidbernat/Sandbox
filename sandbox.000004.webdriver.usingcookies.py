from bs4 import BeautifulSoup
from selenium import webdriver
from multiprocessing import pool
import browsercookie
import requests
import base64
import json
import time
import os

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Do not allow Alphabet to delete your third-party cookies! Cookies are the credible evidence that your browser visited.
# Cookies are the crumbs intentionally remaining after moving across the web, whereby browsers pass information from
# the browser to the computer operating system for longer term storage, and for inference across multiple websites. In
# their modern sense the industry adopted these whereby small piles of data are collected site-by-site for advertising
# intelligence based on user click data, web surfing content, and APIs from backend systems; but nothing unique to the
# advertising industry is here: cookies are used to store passwords, interaction data, user settings, and anything else,
# and are up to the discretion of the site operator. Any website can request to store any particular data on its behalf.
# In returning to the shopping example, when you populate a cart with items on a webpage those are stored in the cookies
# written to your computer regardless of whether you are logged in to the site; that site may assign you a random user
# id which is also written to that cookie, then when you return that site knows you are still accessing that site again
# even if you are not an account holder on that site; most authentication services (such as Firebase) do this
# automatically; these same cookies are sold to advertises worldwide and often pumped back to you through automatic ad
# exchanges run through Google and Meta, which is why those products seem to follow you around in ads to every website.
# Can you imagine ditching every slip of paper in your house just because Amazon told you to get rid of your books now?
# Passwords are also stored: so, when you sign in to the New York Times in Firefox, that site will store a cookie that
# with a generated hash of your password which, once present, will allow you to traverse the site without sighing in
# again. We will use the "cookiejar" associated with Firefox to bypass any need to login but still using Selenium for
# the webdriver; requests and REST APIs have a similar functionality which is more or less identical to the process here.
#
# Despite the massive importance and fortunes of cookies would you be surprised to know its open source packages are
# rudimentary at best? Users searching for Python packages will (20251227) quickly find an unmaintained "browsercookie"
# and a spin-off "browser_cookie3" which is somewhat more maintained for cross-browser support. But, regardless of this
# support, similar features such as "browser-history" are antiquated, not purpose-built for real time, exist with novice
# support communities, and neither histories nor cookies are universally supported for transfer between browsers, making
# switching away or to various browsers at times impossible for casual users to preserve their browser history state
# and its reconstruction for their own use. Would you not expect an AI which knows everything you ever read? I do. And
# with an exception of reconstructing websites back in time, which of course change, cookies are an instrumental force.
#
# Chromium developed by Google is the core engine of nearly every available browser, with alternatives providing veneer
# wrapping to the core Chromium services, nearly a decade ago, with Google sitting directly between DNS and Domain layer
# Internet hardware and the browser, nearly entirely spearheaded by an enterprising then-young Sundar Pichai, smart man.
# A few alternatives exist, but quickly projects become disjointed: Brave Browser, by the creator of Javascript, is now
# positioned for cryptocurrencies and does not integrate its data transfer well to other browsers; Firefox is standard.
# We will use Firefox for all of your webdriver browsing experiences: so go login to New York Times in Firefox browser.
#
# Navigate to the columnist Nicholas Kristof at https://www.nytimes.com/column/nicholas-kristof to see the entire archive
# of his column. We want to download the title, subtitle, url, publication date, and authors of each of his articles.
# Using the inspect method in the browser to find the HTML tags of each of the items: here we want to find each group
# of tags, and then search specifically inside an instance of a group for the particular components wer are looking for.
#
# The dynamics of the user experience is infinite scroll: the site loads a certain number of groups, and when the user
# scrolls to the bottom of the list of groups, the JS will make REST API calls to identify more groups from the database
# and construct the HTML tags at the bottom of the document to continue the scrolling infinitely. So in this example
# what we need to do is emulate scrolling to the bottom of the HTML document so that those REST APIs are triggered,
# wait a moment, and continue parsing the document further; in this example we will configure the webdriver so that
# as long as our parser continues to find larger numbers of article groups our webdriver will continue scrolling further.
# In my experience the parser reaches about 1100 articles and then the New York Times API stops making new calls, which
# runs most columnists archives back to about 2014; and, the HTML tags of interest are identical for each of the columnists.
# The columnist archive lists do not require being logged in and so do not require cookies; so afterward we will use
# our list of individual articles to download a few dozen of their articles and parse those into its text content too.
#
# Lastly, we will use the package BeautifulSoup to parse our HTML to find specific matching tags and their dependencies.
# As previously stated, Selenium is always much slower because its engine completes everything from graphical layouts to
# screenshots to backend system calls executed as those graphical layers are built or execute JS, and in this application
# we are not using any of those features for our parsing and sensemaking. HTML can be parsed as xml and searched by
# those same xpaths e.g. "//div[@class="css-14ee9cx"]//span[@class="css-1n7hynb"]//text()" to identify a specific span
# type within a specific div type and extract its text, but I find this usage fragile and needlessly sensitive to very
# small nuances of unchecked strings (i.e., where in the pipeline are you alerted when you forget a quote of the wrong
# type in the fourth stage down), and much easier to use the very large community BeautifulSoup where one searches for
# tag types, confirms or discards based on attributes, and searches first within, all in iterations of a few lines of
# Python code treating the tags as objects> It is slightly less efficient but I find much more reliably faster to code.

class HtmlNode:

    def __init__(self, tag, classes=None, has_attrs=None, get_attrs=None, expect_one=False):
        if classes is None: classes = []
        if not isinstance(classes, (tuple, list)): classes = [classes]
        if has_attrs is None: has_attrs = dict()
        if get_attrs is None: get_attrs = None  # implies to return the element itself
        self.tag = tag
        self.classes = classes
        self.has_attrs = has_attrs
        self.get_attr = get_attrs
        self.expect_one = expect_one  # this is a lame hack that I would not use in production; when only one result is
                                      # expected, i.e. "headline" I want the result returned as a string not [string].
                                      # it also serves weakly as a data integrity check; but better solutions exist.

    def parse(self, tree):
        results = []
        matching = tree.find_all(self.tag, class_=self.classes)
        if len(matching) == 0: return []
        if self.expect_one and len(matching) != 1:
            raise RuntimeError(f"more tags than expected found={matching}")
        for tag in matching:
            if any([SoupHelpers.get_attr(tag, key) != value for key, value in self.has_attrs]): continue
            if self.get_attr is None:
                results.append(tag)  # return the tag itself
            else:
                to_gets = self.get_attr
                is_one = isinstance(to_gets, str)  # convenience to return value rather than [value] when is str
                if is_one: to_gets = [to_gets]
                if not isinstance(to_gets, (tuple, list)): raise ValueError(f"{to_gets} is not a list, str, or None")
                result = [tag.get_text(" ") if to_get == "__TEXT" else SoupHelpers.get_attr(tag, to_get) for to_get in to_gets]
                if is_one: result = result[0]
                results.append(result)
        return results[0] if self.expect_one else results  # this is also lame


class SoupHelpers:

    @staticmethod
    def get_attr(tag, key, if_not_exists=None):
        """tag is not a dictionary; so does not have tag.get(key); so this makes retrieval easier and without throws"""
        return tag.attrs[key] if tag.has_attr(key) else if_not_exists

class WebRobot:

    @staticmethod
    def driver(headless=True):
        options = webdriver.FirefoxOptions()
        if headless: options.add_argument("--headless")  # run as headless will not render a browser window
        return webdriver.Firefox(options=options)  #  may need to sudo apt install firefox-geckodriver or brew install geckodriver


class SlowlyScrollDownPage:
    # a very simple example of how slightly more realistic scrolling might be implemented inline using an AI
    # in general scrolling at maximum speed has not triggered website backends to restrict surfing due to robotics
    # one can also imagine how large databases of user engagement data, i.e., human CAPTCHA recordings or Firebase
    # Analytics or any software that directly records human mouse movements, could be used here instead as generative
    # AI to emulate countlessly realistic human actions. These models are fundamentally the same as natural language
    # generative AI; and the process of simulating from gathered data goes back decades in math (c.f. Monte Carlo).

    current_position = 0  # in units of y pixel
    n_small_scrolls_per_session = 10
    n_position_change_per_small_scroll = 300

    @staticmethod
    def slowly_scroll_down_page(_driver):
        total_available_height, scroll_i = _driver.execute_script("return document.body.scrollHeight"), 0
        while SlowlyScrollDownPage.current_position <= total_available_height \
                and scroll_i < SlowlyScrollDownPage.n_small_scrolls_per_session:
            SlowlyScrollDownPage.current_position += SlowlyScrollDownPage.n_position_change_per_small_scroll
            _driver.execute_script("window.scrollTo(0, {});".format(SlowlyScrollDownPage.current_position))
            logger.info(f"scroll y={SlowlyScrollDownPage.current_position}")
            total_available_height = _driver.execute_script("return document.body.scrollHeight")
            scroll_i += 1


# url = "https://www.nytimes.com/column/nicholas-kristof"
# url = "https://www.nytimes.com/column/jamelle-bouie"
# url = "https://www.nytimes.com/column/ezra-klein"
# url = "https://www.nytimes.com/column/charles-m-blow"
# url = "https://www.nytimes.com/column/ross-douthat"
# url = "https://www.nytimes.com/column/gail-collins"

# for reading the columnist archives
root = HtmlNode("div", "css-14ee9cx")
components = dict(
    author = HtmlNode("span", "css-1n7hynb", get_attrs="__TEXT", expect_one=True),
    date = HtmlNode("div", "e15t083i3", get_attrs="__TEXT", expect_one=True),
    subtitle = HtmlNode("p", "e15t083i1", get_attrs="__TEXT", expect_one=True),
    headline = HtmlNode("a", "css-8hzhxf", get_attrs="__TEXT", expect_one=True),
    url = HtmlNode("a", "css-8hzhxf", get_attrs="href", expect_one=True))

def parse_columnist_archive(html):
    soup = BeautifulSoup(html, 'html.parser')
    blocks = root.parse(soup)
    return [{field: parser.parse(block) for field, parser in components.items()} for block in blocks]

storage_dir = "_db/_gitignore/sandbox/000004/"
name = "nicholas-kristof"
os.makedirs(storage_dir, exist_ok=True)
url = f"https://www.nytimes.com/column/{name}"
cj = browsercookie.firefox()  # about 0.43 seconds
driver = WebRobot.driver(headless=False)
driver.get(url)


n_found, n_no_change = 0, 0
while True:
    # SlowlyScrollDownPage.slowly_scroll_down_page(driver)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")  # full speed instant scroll
    time.sleep(0.5)
    html = driver.page_source
    articles = parse_columnist_archive(html)
    logger.info(f"found n_found={len(articles)}")
    if n_found < len(articles):
        n_found, n_no_change = len(articles), 0
        with open(os.path.join(storage_dir, f"{name}.json"), "w") as f: json.dump(articles, f)  # save the parsed information
        with open(os.path.join(storage_dir, f"{name}.html"), "w") as f: f.write(html)           # save the url we are pulling from
    else:
        if n_no_change >= 6: break
        n_no_change += 1


# Now let us go through the urls in the headline links and download those in parallel using the cookies in cookiejar


class ParallelizePool:
    """a simple multi-use class for running a function in n_thread parallel protected function calls """
    def __init__(self, n_threads=10):
        self.pool = pool.ThreadPool(processes=n_threads)

    def starmap(self, function, arguments, on_error_value=None, protected_throws=True):
        """execute function for each of arguments [args1, args2...]. returns array of return values or on_error_value"""
        if len(arguments) == 0: return []
        if protected_throws:
            try: results = self.pool.starmap(function, arguments)
            except: results = on_error_value
        else: results = self.pool.starmap(function, arguments)
        return results


components = dict(
    headline = HtmlNode("h1", "e1h9rw200", get_attrs="__TEXT", expect_one=True),
    byline = HtmlNode("div", "epjyd6m1", get_attrs="__TEXT"))  # sometimes there are two
root = HtmlNode("div", "StoryBodyCompanionColumn")  # multiple StoryBodyCompanionColumn each with multiple p
paragraph = HtmlNode("p", "evys1bk0", get_attrs="__TEXT")

# we use emulated header information sent with our requests REST API to more closely emulate the browser experience
browser_headers = {'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148'}
cj = browsercookie.firefox()  # load cookies already in FireFox. Did you log into NYT in FireFox? It will be loaded here.

# this has some stupid bugs because of array[0] but whatever I will polish that when I getback.
# the atomic react problem needs to be posted to forums and I really do not want to use my public identity

def parse_columnist_article(_url):
    start_s = time.perf_counter()
    b64 = base64.b64encode(_url.encode()).decode()  # make a reversible alphanumeric string to name our downloaded file.
    if os.path.exists(os.path.join(storage_dir, f"{b64}.json")): return
    r = requests.get(_url, headers=browser_headers, cookies=cj)  # read cookies for domain nytimes.com at request time
    r.raise_for_status()  # check whether error

    soup = BeautifulSoup(r.text)
    data = {field: parser.parse(soup) for field, parser in components.items()}  # headline and byline
    paragraphs = [p for story in root.parse(soup) for p in paragraph.parse(story)]
    data = data | dict(text="\n\n".join(paragraphs), url=_url, b64=b64)
    with open(os.path.join(storage_dir, f"{b64}.json"), "w") as f: json.dump(data, f)
    with open(os.path.join(storage_dir, f"{b64}.html"), "w") as f: f.write(r.text)
    logging.info(f"n_paragraphs={len(paragraphs)} time_ts={time.perf_counter()-start_s} url={_url}")

with open(os.path.join(storage_dir, f"{name}.json"), "r") as f: articles = json.load(f)
args = [["https://www.nytimes.com" + data["url"]] for data in articles]
parallel = ParallelizePool(n_threads=5)
results = parallel.starmap(parse_columnist_article, args)

