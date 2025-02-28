from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# PROBLEM 20250227: REPORTED.


# Robotic downloading of content from webpages generally requires one of two mechanisms: either webpages are static or
# specifically written as the endpoint of REST APIs, in which case direct HTTP REST requests can be made; or, webpages
# are dynamic or loading from multiple of their own service calls and require simulated browser experiences known as a
# webdriver. The latter is slower, simulates an entire browser, and can emulate all user input actions and more; and is
# also single-threaded, meaning that at most one operator can operate at a time for each instance of the program. (The
# requests REST API method can easily be written to run in ten-fold parallelizing without websites triggering their
# robotic security systems, making requests ten to twenty times faster to download content for the same length of effort
# to write the program.) The webdriver approach is the actual webbrowser experience driven by a robotic web surfer user.
#
# Here we simulate a user surfing to the Pennsylvania State Parks website, clicking on Find A Park, navigating to its
# searchbar to trigger a query, and downloading the results as a structured list, including pagination to deeper pages
# of results. This example was originally written to demonstrate how to login to a website before interacting with its
# products pages, which are accessible only behind a login, but the action of populating a username and password field
# and waiting for the resulting page to load is identical in all meaningful ways. The example was originally written for
# the CenterWell Pharmacy to download its OTC products to build an internal app that allows our family to interact with
# a private deep learning AI agent to discuss and inform on product decisions, populate a local table of products to
# purchase with our monthly stipend, and then trigger a new robotic webdriver instance to login to populate our cart,
# with the purchase action loaded for us to click to confirm. We will make components of our internal app available to
# the public, including in an upcoming sandbox in which we provide the deep learning agent and the interactive table UI.
# We did not feel it was right to use proprietary data in our example and did not want to endorse a vendor e.g. Amazon.
# However the same process for launching into Amazon to download all products from a search query is essentially the same.
#
# How do we determine what to instruct the webdriver to do? In most cases without AI engines making those decisions in
# real-time, we do this by providing strict rule-based decisions to make after inspecting the page somewhat manually.
# In brief, there are only a small number of tools we need to use. Every element on a webpage is represented by an HTML
# tag (p for text, span and div for groups of tags, button form input to input data, a for links; and otherwise every tag
# can be assigned actions to occur 'onclick' as buttons or when scrolling etc., but more or less everything buckets into
# these items). Each tag is further described by an optional class field (more or less a categorical typing system used
# for styling items similarly) and an implicit id field (a unique identifier for that specific instance of a tag). After
# that everything else is more dynamic manipulations of those HTML tags using script compute called Javascript, and the
# standards have nearly all been written down since the origins of HTML decades ago and can be read of at w3schools.com.
# Furthermore, because HTML is an open standard even browser lets you easily see the HTML and inbound/outbound traffic.
#
# Navigate to https://www.pa.gov/agencies/dcnr/recreation/where-to-go/state-parks.html (20250227) and scroll to the
# "Find a park" button and right-click to select Inspect; a side window (Chrome) or bottom window (Firefox) will open
# and show you the exact HTML tag that renders those components. As you scroll overtop of various tags they will be
# highlighted on the webpage to show you what groups of elements they encapsulate; you cannot break anything so dive in.
# My browser shows that the button is built most primarily using an "a" tag and class="cmp-button" along with other
# information though I will choose to find this button below by searching for an "a" tag with text="Find a park". Why
# will become more apparent as we walk through collecting the rest of the data we need. Click on the button to go to
# the Find A State Park search page. (Yes, in this instance we could have started our browser here as well.) Inspect
# the search bar input field and search button: mine shows an "input" tag with part="input" attribute for the search
# field and "button" tag with part="submit-button" for the button so we will use those. Here is why: generally speaking
# we are looking for specific tags and clear attributes that were written by the developer to uniquely characterize that
# specific HTML element. In the modern web software packages for designing HTML often will auto-generate unique but
# random class and id fields: a headline url on one newspaper site might be 'rfba' but 'div-gtfr' on another, which
# complicates the reuse of these tools; or, 'rfba' for one headline and 'fntb' for another headline on the same page.
# But generally speaking all elements of the same syntactic design (i.e., all headline elements, all product elements)
# from the same vendor (i.e., PA Parks, or NYT) will have some identifying unique element syntax that is not difficult
# to find out with a little poking around and trial and error; and, yes, this can be done by automation AI itself too.
# Manually search for "creek" because this was the first search term I found that has at least two pages of results.
# Navigate to one of its search results. I find the following information for the following relevant fields of data:
# Each result is contained in an "atomic-result" tag of class="result-component hydrated" (this means that the tag is
# of two classes, "result-component" and "hydrated"; and we will end up using only the first one. The park name is
# "atomic-result-text" field="copapwptitle" and the address field="copapwpaddressline1" and field="copapwpwcitystatezip"
# and the link to the park specific page is an "a" tag inside a field="copapwplinkurl1". Tedious, yes; but not too hard.
#
# Lastly, there are ways the webdriver itself interacts with the website system; generally speaking there are only a
# small set of actions: search through tags for a matching condition, populate a tag value or emulate a click or scroll,
# wait for actions to occur or pages to load, wait upon a condition to be met, or navigate to a new url entirely. Each
# of those is a fairly straightforward process and when robotic operators fail it is usually either a timing issue with
# some website action happening in an unexpected order or too slowly, in which case simply try again; or the website
# has changed in some way that mandates building a new user following the same roughly guided outline of an approach.
# Remember first and foremost that the robotic operator is dumb and does not know anything: when you navigate to a page
# that says in big letters "page not found" or redirects to some landing page the robotic operator has no idea what
# that means or what to do in that situation unless you code that into your system or plug in an AI operator with its
# own command options such as "jump back three points in the process and try again" or "try a new search term" etc.

# Note: you will need to install chrome webdriver (sudo apt install chromium-chromedriver or brew install chromedriver)
# and then find its path at the end of the installation instructions. And, lastly these instructions are what would be
# used to login to the CenterWell Pharmacy were we walking through that example; but for completeness here they are. But
# at first blush from the description of this tutorial you should be able to read along in what they are designed to do.
# driver.get("https://account.centerwellpharmacy.com/")
# username_field = driver.find_element(By.CSS_SELECTOR, 'input[name="username"]')
# password_field = driver.find_element(By.CSS_SELECTOR, 'input[name="password"]')
# submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
# username_field.send_keys(username)
# password_field.send_keys(password)
# submit_button.click()

# update these and then post.
#    wait.until(EC.element_to_be_clickable((By.ID, 'langSelect-EN'))).click()
# element_to_be_clickable
# visibility_of_element_located
# presence_of_element_located
# wait.until(EC.element_to_be_clickable((By.ID, 'langSelect-EN'))).click()

webdriver_chrome_path = "/opt/homebrew/bin/chromedriver"

class WebRobot:

    @staticmethod
    def driver(headless=True):
        options = webdriver.chrome.options.Options()
        if headless: options.add_argument("--headless")  # run as headless will not render a browser window
        return webdriver.Chrome(options=options, service=webdriver.chrome.service.Service(webdriver_chrome_path))

    @staticmethod
    # This is a generic function for finding a specific element which returns the element when found or False when not yet.
    def wait_for_element(_driver, how, s):  # EC.presence_of_element_located()
        try: return _driver.find_element(how, s)
        except: return False

    @staticmethod
    # This does the same as .wait_for_element but waits for multiple elements
    def wait_for_elements(_driver, how, s):  # could use EC.presence_of_element_located()
        try: return _driver.find_elements(how, s)
        except: return False

    @staticmethod
    def get_all_attributes(_driver, element):
    # There is no other way to get all the elements of a field as per: https://stackoverflow.com/a/27307235/5573074
        return _driver.execute_script('var items = {}; for (index = 0; index < arguments[0].attributes.length; ++index) { items[arguments[0].attributes[index].name] = arguments[0].attributes[index].value }; return items;', element)


url = "https://www.pa.gov/agencies/dcnr/recreation/where-to-go/state-parks.html"

driver = WebRobot.driver(headless=False)  # true will render the browser invisible and faster

# Selenium webdriver will already wait until document.readyState == "complete" which is an event triggered once the page
# HTML and JS have loaded, but does not account for many events such as the page waiting to hear back from backend
# databases with products to populate the HTML using; i.e., in such an instance your program would fail implicitly by
# returning zero products but otherwise function correctly. Generally speaking there are three ways to know whether
# Selenium has finished loading the url in the way you have very likely designed the function to operate:
# 1. presence of element: JS can also create HTML tags; so, is the element you expect to be there in the HTML yet?
# 2. element to be clickable: JS can add functionality to tags; so, does the element have expected attributes too?
# 3. visibility of element: often designers will create tags to always exist, then populate dynamically from backends
# Most everything about building a dynamic robotic operator is completed by what we defined here and above.

# WebDriverWait checks every 0.5 seconds whether our function WebRobot.wait_for_element returns not-False or False, for
# up to 30 seconds before declaring itself an error. The "//a[...]" is called an XPATH which represents a mechanism for
# searching for specific elements in an HTML (in this case an "a" tag) that also match a conditional expression (in
# this case the normalized inner tag of the text exactly matching "Find a Park". Yes this can be persnickety to build.
# (My first run-through failed because I searched for 'Find a park' instead of 'Find a Park'. Computers are like that.)
driver.get(url)
link_find_a_park = WebDriverWait(driver, timeout=30).until(
    lambda _driver: WebRobot.wait_for_element(_driver, By.XPATH, "//a[normalize-space()='Find a Park']"))


# in our case the "Find a Park" is not per se a "button" but rather a commonplace URL link in a "div" tag designed and
# reshaped to be visually rendered as a button-like object. so to proceed we do not 'click' instead we navigate to url.
url = link_find_a_park.get_attribute("href")  # href stands for hypertext reference (i.e., "url of the link")
driver.get(url)
exit()
# sourcecode = self.driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML')
element_input = WebDriverWait(driver, timeout=30).until(
    lambda _driver: WebRobot.wait_for_elements(_driver, [
        [By.CSS_SELECTOR, 'input[part="input"]'],
        [By.CSS_SELECTOR, 'atomic-result-text[field="copapwptitle"]'],
    ]))  # a problem occurred

