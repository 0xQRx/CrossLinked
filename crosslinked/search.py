import logging
import requests
import threading
from time import sleep
from random import choice
from bs4 import BeautifulSoup
from unidecode import unidecode
from urllib.parse import urlparse
from crosslinked.logger import Log
from datetime import datetime, timedelta
from urllib3 import disable_warnings, exceptions

disable_warnings(exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.WARNING)
csv = logging.getLogger('cLinked_csv')


class Timer(threading.Thread):
    def __init__(self, timeout):
        threading.Thread.__init__(self)
        self.start_time = None
        self.running = None
        self.timeout = timeout

    def run(self):
        self.running = True
        self.start_time = datetime.now()
        logging.debug("Thread Timer: Started")

        while self.running:
            if (datetime.now() - self.start_time) > timedelta(seconds=self.timeout):
                self.stop()
            sleep(0.05)

    def stop(self):
        logging.debug("Thread Timer: Stopped")
        self.running = False


class CompanySearch:
    def __init__(self, domain, conn_timeout=20, proxies=[], jitter=1):
        self.results = []
        self.url = 'https://www.google.com/search?q=site:linkedin.com+intext:"{}"&num=1'
        self.domain = domain
        self.conn_timeout = conn_timeout
        self.proxies = proxies
        self.jitter = jitter

    def search(self):
        try:
            url = self.url.format(self.domain, 0)
            resp = web_request(url, self.conn_timeout, self.proxies)
            http_code = get_statuscode(resp)

            if http_code != 200:
                Log.warn('None 200 response, exiting search ({})'.format(http_code))
                return None

            self.page_parser(resp)
            
            sleep(self.jitter)
            
            if self.results:
                company_name = self.results[0]
                print(company_name)
                return company_name
            else:
                Log.warn('No company name found for domain: {}'.format(self.domain))
                return None
                
        except Exception as e:
            Log.warn('Search failed: {}'.format(e))
            return None

    def page_parser(self, resp):
        for link in extract_links(resp):
            try:
                self.results_handler(link)
                if self.results:  # Stop after finding first company name
                    break
            except Exception as e:
                Log.warn('Failed Parsing: {}- {}'.format(link.get('href'), e))

    def results_handler(self, link):
        url = str(link.get('href')).lower()

        if not extract_subdomain(url).endswith('linkedin.com'):
            return False
        elif 'linkedin.com/company/' not in url:
            return False

        company_name = self.extract_company_name(link)
        if company_name:
            self.results.append(company_name)

    def extract_company_name(self, link):
        h3_tag = link.find('h3')
        if h3_tag:
            return h3_tag.get_text().strip()
        return None


class CrossLinked:
    def __init__(self, search_engine, target, timeout, conn_timeout=3, proxies=[], jitter=0):
        self.results = []
        self.url = {'google': 'https://www.google.com/search?q=site:linkedin.com/in+"{}"&num=100&start={}',
                    'bing': 'http://www.bing.com/search?q="{}"+site:linkedin.com/in&first={}'}

        self.runtime = datetime.now().strftime('%m-%d-%Y %H:%M:%S')
        self.search_engine = search_engine
        self.conn_timeout = conn_timeout
        self.timeout = timeout
        self.proxies = proxies
        self.target = target
        self.jitter = jitter

    def search(self):
        search_timer = Timer(self.timeout)
        search_timer.start()

        while search_timer.running:
            try:
                url = self.url[self.search_engine].format(self.target, len(self.results))
                resp = web_request(url, self.conn_timeout, self.proxies)
                http_code = get_statuscode(resp)

                if http_code != 200:
                    Log.info("{:<3} {} ({})".format(len(self.results), url, http_code))
                    Log.warn('None 200 response, exiting search ({})'.format(http_code))
                    break

                self.page_parser(resp)
                Log.info("{:<3} {} ({})".format(len(self.results), url, http_code))

                sleep(self.jitter)
            except KeyboardInterrupt:
                Log.warn("Key event detected, exiting search...")
                break

        search_timer.stop()
        return self.results

    def page_parser(self, resp):
        for link in extract_links(resp):
            try:
                self.results_handler(link)
            except Exception as e:
                Log.warn('Failed Parsing: {}- {}'.format(link.get('href'), e))

    def link_parser(self, url, link):
        u = {'url': url}
        u['text'] = unidecode(link.text.split("|")[0].split("...")[0])  # Capture link text before trailing chars
        u['title'] = self.parse_linkedin_title(u['text'])               # Extract job title
        u['name'] = self.parse_linkedin_name(u['text'])                 # Extract whole name
        return u

    def parse_linkedin_title(self, data):
        try:
            title = data.split("-")[1].split('https:')[0]
            return title.split("...")[0].split("|")[0].strip()
        except:
            return 'N/A'

    def parse_linkedin_name(self, data):
        try:
            name = data.split("-")[0].strip()
            return unidecode(name).lower()
        except:
            return False

    def results_handler(self, link):
        url = str(link.get('href')).lower()

        if not extract_subdomain(url).endswith('linkedin.com'):
            return False
        elif 'linkedin.com/in' not in url:
            return False

        data = self.link_parser(url, link)
        self.log_results(data) if data['name'] else False


    def log_results(self, d):
        # Prevent Duplicates & non-standard responses (i.e: "<span>linkedin.com</span></a>")
        if d in self.results:
            return
        elif 'linkedin.com' in d['name']:
            return

        self.results.append(d)
        # Search results are logged to names.csv but names.txt is not generated until end to prevent duplicates
        logging.debug('name: {:25} RawTxt: {}'.format(d['name'], d['text']))
        csv.info('"{}","{}","{}","{}","{}","{}",'.format(self.runtime, self.search_engine, d['name'], d['title'], d['url'], d['text']))


def get_statuscode(resp):
    try:
        return resp.status_code
    except:
        return 0


def get_proxy(proxies):
    tmp = choice(proxies) if proxies else False
    return {"http": tmp, "https": tmp} if tmp else {}


def get_agent():
    return choice([
        # Chrome (Windows/macOS/Linux)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36',

        # Firefox (Windows/macOS/Linux)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13.4; rv:126.0) Gecko/20100101 Firefox/126.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0',

        # Safari (macOS)
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',

        # Safari (iOS)
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',

        # Edge (Chromium-based)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36 Edg/125.0.2535.67',

        # Chrome on Android
        'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Mobile Safari/537.36',
        'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Mobile Safari/537.36',

        # Firefox on Android
        'Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0',

        # Samsung Internet (Android)
        'Mozilla/5.0 (Linux; Android 13; SM-G998U) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/125.0.6422.113 Mobile Safari/537.36',

        # Brave (Chromium)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36 Brave/125.1.63.113',

        # Opera (Chromium-based)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36 OPR/110.0.5100.67',

        # Vivaldi (Chromium-based)
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Safari/537.36 Vivaldi/6.7.3329.25',

        # Tor Browser (based on Firefox)
        'Mozilla/5.0 (Windows NT 10.0; rv:102.0) Gecko/20100101 Firefox/102.0'
    ])


def web_request(url, timeout=3, proxies=[], **kwargs):
    try:
        s = requests.Session()
        r = requests.Request('GET', url, headers={'User-Agent': get_agent()}, cookies = {'CONSENT' : 'YES'}, **kwargs)
        p = r.prepare()
        return s.send(p, timeout=timeout, verify=False, proxies=get_proxy(proxies))
    except requests.exceptions.TooManyRedirects as e:
        Log.fail('Proxy Error: {}'.format(e))
    except:
        pass
    return False


def extract_links(resp):
    links = []
    soup = BeautifulSoup(resp.content, 'lxml')
    for link in soup.findAll('a'):
        links.append(link)
    return links


def extract_subdomain(url):
    return urlparse(url).netloc
