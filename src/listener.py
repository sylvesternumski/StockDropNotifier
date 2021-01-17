from telegram_bots.sender import Sender
from parsers.newegg_parser import NeweggParser as Parser
from datetime import datetime
from datetime import timedelta
import time
import requests
import os
import yaml
import argparse
import logging

class Listener:
    
    def __init__(self, path_to_config):
        self.start_time = time.time()
        self.config = self.load_config(path_to_config)
        path_to_telegram_config = self.config['path_to_telegram_config']
        self.sender = Sender(path_to_telegram_config)
        self.chat_id = self.config['chat_id']
        self.search_words = self.config['search_words']
        self.search_words = [word.lower() for word in self.search_words]
        self.forbidden_words = self.config['forbidden_words'] 
        self.forbidden_words = [word.lower() for word in self.forbidden_words]
        self.price_ceiling = self.config['price_ceiling']
        self.rest_time = self.config['rest_time']
        self.request_frequency = self.config['request_frequency']
        self.update_interval = self.config['update_interval']
        self.needs_update = True
        self.parser = Parser()
        self.name = ''.join('[{}]'.format(word) for word in self.search_words)
        self.get_page_time = time.time()

        self.load_logger()
        self.send_msg('{} bot starts running'.format(self.name))

    def load_logger(self):
        if not os.path.exists('log/listener_log/user_{}'.format(self.chat_id)):
            os.popen('mkdir log/listener_log/user_{}'.format(self.chat_id))
        path_to_log = 'log/listener_log/user_{}/{}.log'.format(self.chat_id, self.name)
        os.popen('touch {}'.format(path_to_log))
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                            level=logging.INFO, filename=path_to_log)

    def load_config(self, path_to_config):
        with open(path_to_config, 'r') as handler:
            config = yaml.full_load(handler)
        return config

    def update_url_list(self):
        run_hrs, _ , _ = self.runtime()
        self.needs_update = self.needs_update or run_hrs % self.update_interval != 0
        if self.needs_update and run_hrs % self.update_interval == 0:
            self.generate_url()
            self.needs_update = False

    def get_rest_time(self):
        curr_time = datetime.now()
        rest_start = curr_time.replace(hour=self.rest_time[0], minute=0, second=0, microsecond=0)
        rest_end = curr_time.replace(hour=self.rest_time[1], minute=0, second=0, microsecond=0)
        if self.rest_time[0] > self.rest_time[1]:
            rest_end = rest_end + timedelta(days = 1)
        if curr_time > rest_start and curr_time < rest_end:
            logging.info('listener will sleep until {}.'.format(rest_end.time()))
            rest_time = (rest_end - curr_time).total_seconds()
        else:
            rest_time = 0
        return rest_time


    def generate_url(self):
        self.product_urls = []
        # generate product urls for each search word
        for word in self.search_words:
            # get product index urls
            search_url = self.parser.get_search_url(word)
            product_index_urls = self.parser.get_product_index_urls(search_url, self.get_page(search_url))
            # get product urls
            for product_index_url in product_index_urls:
                self.product_urls.extend(self.parser.get_product_urls(self.get_page(product_index_url)))

    def scan_url(self):
        # iterate through self.product_url list
        bad_urls = []
        for product_url in self.product_urls:
            try:
                product_page = self.get_page(product_url)
                # get name, dealer, price, and stock info from product page
                name = self.parser.get_name(product_url, product_page).lower()
                dealer = self.parser.get_dealer(product_url, product_page)
                price = self.parser.get_price(product_url, product_page)
                is_in_stock = self.parser.get_inventory(product_url, product_page)
                # check whether product's name is valid
                name_is_valid = True
                for word in self.forbidden_words:
                    if word in name.split():
                        name_is_valid = False
                        break
                # send stock if product's name is valid and it is in stock and it is cheaper than price ceiling
                if price <= self.price_ceiling and name_is_valid:
                    if is_in_stock:
                        self.send_stock(product_url, price, dealer)
                else:
                    logging.info('remove {} for it is invalid'.format(product_url))
                    bad_urls.append(product_url)
            except Exception as e: 
                # if this url causes an exception, append it to bad_urls
                logging.warning('remove {} for it causes exception'.format(product_url))
                bad_urls.append(product_url)
        # remove all urls in bad_urls from self.product_urls
        if len(bad_urls) != 0:
            for bad_url in bad_urls:
                self.product_urls.remove(bad_url)
    
    def get_page(self, url):
        # control frequency
        duration = time.time() - self.get_page_time
        time.sleep(max(1/self.request_frequency - duration, 0))
        self.get_page_time = time.time()
        # get page from request
        req = requests.get(url, timeout=5)
        page = req.text
        return page

    def time(self):
        return time.time() - self.start_time
    
    def runtime(self):
        run_time = self.time()
        run_secs = int(run_time % 60)
        run_mins = int((run_time % 3600) / 60)
        run_hrs = int(run_time / 3600)
        return run_hrs, run_mins, run_secs

    def send_stock(self, url, price, dealer):
        msg = 'Stock Refilled!\nDealer:{}\nPrice:{}\nURL:{}'.format(dealer, price, url)
        self.send_msg(msg)			

    def send_msg(self, msg):
        self.sender.send_message(msg, self.chat_id)
    
    def run(self):
        try:
            while True:
                # update the url list
                self.update_url_list()
                logging.info('current url list contains {} urls.'.format(len(self.product_urls)))
                # terminate this listener if there are no urls left
                if len(self.product_urls) == 0:
                    self.send_msg('url list to listen is empty. {} bot stops working.'.format(self.name))
                    break	
                # take a rest
                time.sleep(self.get_rest_time())
                # continue to scan
                self.scan_url()
        except Exception as e:
                # an unexpected exception occurred, notify the user and terminate this process
                self.send_msg('AN INTERNAL ERROR OCCURED. {} bot ABORTS.\nERROR MSG: {}'.format(
                self.name, str(e)))
                logging.error(str(e))

def main():
    parser = argparse.ArgumentParser(description='fire up a listener with the filter specified in config')
    parser.add_argument('--config', type=str, help='config file path')
    args = parser.parse_args()
    config = args.config
    listener = Listener(config)
    listener.run()

if __name__ == '__main__':
    main()
