# ！/usr/bin/python3
# -*- coding: utf-8 -*-

import re
import logging
import requests
from utils.cookie import cookies_raw2jar
from utils.extend_descr import ExtendDescr
from bs4 import BeautifulSoup

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


class NexusPHP(object):
    url_host = "http://www.pt_domain.com"  # No '/' at the end.
    db_column = "tracker.pt_domain.com"  # The column in table,should be as same as the first tracker's host

    uplver = "yes"
    encode = "bbcode"  # bbcode or html
    status = False
    auto_thank = True

    session = requests.Session()

    def __init__(self, setting: set, site_setting: dict, tr_client, db_client):
        self._setting = setting
        self.site_setting = site_setting
        self.passkey = site_setting["passkey"]
        try:
            self.status = site_setting["status"]
            self.auto_thank = site_setting["auto_thank"]
            if not site_setting["anonymous_release"]:
                self.uplver = "no"
        except KeyError:
            pass

        self.tc = tr_client
        self.db = db_client
        self.descr = ExtendDescr(setting=self._setting)  # TODO Separate(It's not good idea to assign in every autoseed)

        if self.status:
            self.login()

    def model_name(self):
        return type(self).__name__

    # -*- Login info site,and check login's info. -*-
    def login(self):
        login_dict = self.site_setting["login"]
        try:
            account_dict = login_dict["account"]
            for pair, key in account_dict.items():
                if key in [None, ""]:
                    raise KeyError("One more account key(maybe username or password) is not filled in.")
            post_data = self.login_data(account_dict)
            self.session.post(url="{host}/takelogin.php".format(host=self.url_host), data=post_data)
        except KeyError as err:
            logging.error("Account login error: \"{err}\".Use cookies install.".format(err=err.args))
            cookies = cookies_raw2jar(login_dict["cookies"])
            self.session.headers.update(cookies)
        else:
            self.session_check()

    def session_check(self):
        page_usercp_bs = self.get_page(url="{host}/usercp.php".format(host=self.url_host), bs=True)
        info_block = page_usercp_bs.find(id="info_block")
        if info_block:
            user_tag = info_block.find("a", href=re.compile("userdetails.php"), class_=re.compile("Name"))
            up_name = user_tag.get_text()
            logging.debug("Model \"{mo}\" is activation now.You are assign as \"{up}\" in this site."
                          "Anonymous release: {ar},auto_thank: {at}".format(mo=self.model_name(), up=up_name,
                                                                            ar=self.uplver, at=self.auto_thank))
        else:
            self.status = False
            logging.error("Can not verify identity.If you want to use \"{mo}\","
                          "please exit and Check".format(mo=self.model_name()))

    # -*- Encapsulation requests's method,with format-out as bs or json when use get -*-
    def get_page(self, url, params=None, bs=False, json=False):
        page = self.session.get(url=url, params=params)
        return_info = page.text
        if bs:
            return_info = BeautifulSoup(return_info, "lxml")
        elif json:
            return_info = page.json()
        return return_info

    def post_data(self, url, data=None, files=None):
        return self.session.post(url=url, data=data, files=files)

    # -*- Torrent's download, upload and thank -*-
    def torrent_download(self, tid, thanks=auto_thank):
        download_url = "{host}/download.php?id={tid}&passkey={pk}".format(host=self.url_host, tid=tid, pk=self.passkey)
        added_torrent = self.tc.add_torrent(torrent=download_url)
        logging.info("Download Torrent OK,which id: {id}.".format(id=tid))
        if thanks:  # Automatically thanks for additional Bones.
            self.torrent_thank(tid)
        return added_torrent.id

    def torrent_upload(self, data: tuple):
        upload_url = "{host}/takeupload.php".format(host=self.url_host)
        post = self.post_data(url=upload_url, files=data)
        if post.url != upload_url:  # 发布成功检查
            seed_torrent_download_id = re.search("id=(\d+)", post.url).group(1)  # 获取种子编号
            flag = self.torrent_download(tid=seed_torrent_download_id)
            logging.info("Reseed post OK,The torrent's in transmission: {fl}".format(fl=flag))
            # TODO USE new torrent's id to Update `info_list` in db
        else:  # 未发布成功打log
            outer_bs = BeautifulSoup(post.text, "lxml").find("td", id="outer")
            if outer_bs.find_all("table"):  # Remove unnecessary table info(include SMS,Report)
                for table in outer_bs.find_all("table"):
                    table.extract()
            outer_message = outer_bs.get_text().replace("\n", "")
            flag = -1
            logging.error("Upload this torrent Error,The Server echo:\"{0}\",Stop Posting".format(outer_message))
        return flag

    def torrent_thank(self, tid):
        self.post_data(url="{host}/thanks.php".format(host=self.url_host), data={"id": str(tid)})

    # -*- Get page detail.php, torrent_info.php, torrents.php -*-
    def page_torrent_detail(self, tid, bs=False):
        return self.get_page(url="{host}/details.php".format(host=self.url_host), params={"id": tid, "hit": 1}, bs=bs)

    def page_torrent_info(self, tid, bs=False):
        return self.get_page(url="{host}/torrent_info.php".format(host=self.url_host), params={"id": tid}, bs=bs)

    def page_search(self, payload: dict, bs=False):
        return self.get_page(url="{host}/torrents.php".format(host=self.url_host), params=payload, bs=bs)

    def search_first_torrent_id(self, key, tid=0) -> int:
        bs = self.page_search(payload={"search": key}, bs=True)
        first_torrent_tag = bs.find("a", href=re.compile("download.php"))
        if first_torrent_tag:  # If exist
            href = first_torrent_tag["href"]
            tid = re.search("id=(\d+)", href).group(1)  # 找出种子id
        return tid

    def extend_descr(self, torrent, info_dict) -> str:
        return self.descr.out(raw=info_dict["descr"], torrent=torrent, encode=self.encode,
                              before_torrent_id=info_dict["before_torrent_id"])

    def exist_judge(self, search_title, torrent_file_name) -> int:
        """
        If exist in this site ,return the exist torrent's id,else return 0.
        (Warning:if the exist torrent is not same as the pre-reseed torrent ,will return -1)
        """
        tag = self.search_first_torrent_id(key=search_title)
        if tag is not 0:
            torrent_file_page = self.page_torrent_info(tid=tag, bs=True)
            torrent_file_info_table = torrent_file_page.find("div", align="center").find("table")
            torrent_title = re.search("\\[name\] \(\d+\): (?P<name>.+?) -", torrent_file_info_table.text).group("name")
            if torrent_file_name != torrent_title:  # Use pre-reseed torrent's name match the exist torrent's name
                tag = -1
        return tag

    # -*- The feeding function -*-
    def feed(self, torrent, torrent_info_search, flag=-1):
        logging.info("Autoseed-{mo} Get A feed torrent: {na}".format(mo=self.model_name(), na=torrent.name))
        key_raw = re.sub(r"[_\-.]", " ", torrent_info_search.group("search_name"))
        key_with_ep = "{search_key} {epo} {gr}".format(search_key=key_raw, epo=torrent_info_search.group("episode"),
                                                       gr=torrent_info_search.group("group"))

        search_tag = self.exist_judge(key_with_ep, torrent.name)
        if search_tag == 0:  # 种子不存在，则准备发布
            clone_id = self.db.get_data_clone_id(key=key_raw, site=self.db_column)
            if clone_id in [None, 0, "0"]:
                logging.warning("Not Find clone id from db of this torrent,May got incorrect info when clone.")
                clone_id = self.search_first_torrent_id(key=key_raw)
            else:
                logging.debug("Get clone id({id}) from db OK,USE key: \"{key}\"".format(id=clone_id, key=key_raw))

            torrent_raw_info_dict = self.torrent_clone(clone_id)
            if torrent_raw_info_dict:
                logging.info("Begin post The torrent {0},which name: {1}".format(torrent.id, torrent.name))
                multipart_data = self.data_raw2tuple(torrent, torrent_info_search, torrent_raw_info_dict)
                flag = self.torrent_upload(data=multipart_data)
            else:
                logging.error("Something may wrong,Please check torrent raw dict.Some info may help you:"
                              "search_key: {key}, pattern: {pat}, search_tag: {tag}, "
                              "clone_id: {cid} ".format(key=key_raw, pat=key_with_ep, tag=search_tag, cid=clone_id))
        elif search_tag == -1:  # 如果种子存在，但种子不一致
            logging.warning("Find dupe,and the exist torrent is not same as pre-reseed torrent.Stop Posting~")
        else:  # 如果种子存在（已经有人发布）  -> 辅种
            flag = self.torrent_download(tid=search_tag, thanks=False)
            logging.warning("Find dupe torrent,which id: {0},Automatically assist it~".format(search_tag))

        self.db.reseed_update(did=torrent.id, rid=flag, site=self.db_column)
        return flag

    # -*- At least Overridden function,Please overridden below when add a new site -*-
    def login_data(self, account_dict):  # If you want to login by account but not cookies
        raise KeyError("Unsupported method.")

    def torrent_clone(self, tid) -> dict:
        pass

    def data_raw2tuple(self, torrent, torrent_name_search, raw_info: dict):
        return ()
