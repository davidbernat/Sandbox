from selenium import webdriver
from bs4 import BeautifulSoup
from lxml import etree
import browsercookie

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PROBLEM 20250227: REPORTED.

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
# Navigate to the columnist Nicholas Kristof at https://www.nytimes.com/by/nicholas-kristof to see the entire archive
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
root = '//div[@class="css-14ee9cx"]'
components = dict(
    author = '//span[@class="css-1n7hynb"]/text()',
    date = '//div[@class="e15t083i3"]/text()',
    subtitle = '//p[@class="e15t083i1"]/text()',
    headline = '//a[@class="css-8hzhxf"]/text()',
    url = '//a[@class="css-8hzhxf"]/@href')

webdriver_chrome_path = "/opt/homebrew/bin/chromedriver"

class WebRobot:

    @staticmethod
    def driver(headless=True):
        options = webdriver.chrome.options.Options()
        if headless: options.add_argument("--headless")  # run as headless will not render a browser window
        return webdriver.Chrome(options=options, service=webdriver.chrome.service.Service(webdriver_chrome_path))

    @staticmethod
    # This is a generic function for finding a specific element which returns the element when found or False when not yet.
    def wait_for_element(_driver, how, s):
        try: return _driver.find_element(how, s)
        except: return False

    @staticmethod
    def protected_find_element(_driver, how, s, not_found_value=None):
        try: return _driver.find_element(how, s)
        except: return not_found_value


def parse_columnist_archive(html):
    soup = BeautifulSoup(html, 'lxml')
    dom = etree.HTML(str(soup))
    _roots = dom.xpath(root)
    [r.xpath('//a[@class="css-8hzhxf"]/text()') for r in _roots]
    data = [{field: r.xpath(s) for field, s in components.items()} for r in _roots]
    # a problem occurred


url = "https://www.nytimes.com/by/nicholas-kristof"
# url = "https://www.nytimes.com/by/jamelle-bouie"
# url = "https://www.nytimes.com/by/ezra-klein"
# url = "https://www.nytimes.com/column/charles-m-blow"
# url = "https://www.nytimes.com/by/ross-douthat"
# url = "https://www.nytimes.com/by/gail-collins"


cj = browsercookie.firefox()  # about 0.43 seconds
driver = WebRobot.driver(headless=False)
driver.get(url)

while True:
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    driver.implicitly_wait(0.5)
    html = driver.page_source
    parse_columnist_archive(html)

    exit()  # a problem occurred
