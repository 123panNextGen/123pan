# https://github.com/123panNextGen/123pan
# src/api.py

import os
import json
import hashlib
import requests
import time
import random
import re
import uuid
import threading
import concurrent.futures
from log import get_logger
from config import ConfigManager

logger = get_logger(__name__)


class Pan123:
    """123云盘API客户端类"""
    
    def __init__(
            self,
            readfile=True,
            user_name="",
            pass_word="",
            authorization="",
            input_pwd=False,
    ):

        self.all_device_type = [
            "MI-ONE PLUS", "MI-ONE C1", "MI-ONE", "2012051", "2012053", "2012052", "2012061", "2012062", "2013012",
            "2013021", "2012121", "2013061", "2013062", "2013063", "2014215", "2014218", "2014216", "2014719",
            "2014716", "2014726", "2015015", "2015561", "2015562", "2015911", "2015201", "2015628", "2015105",
            "2015711", "2016070", "2016089", "MDE2", "MDT2", "MCE16", "MCT1", "M1804D2SE", "M1804D2ST", "M1804D2SC",
            "M1803E1A", "M1803E1T", "M1803E1C", "M1807E8S", "M1807E8A", "M1805E2A", "M1808D2TE", "M1808D2TT",
            "M1808D2TC", "M1808D2TG", "M1902F1A", "M1902F1T", "M1902F1C", "M1902F1G", "M1908F1XE", "M1903F2A",
            "M1903F2G", "M1903F10G", "M1903F11G", "M1904F3BG", "M2001J2E", "M2001J2G", "M2001J2I", "M2001J1E",
            "M2001J1G", "M2002J9E", "M2002J9G", "M2002J9S", "M2002J9R", "M2007J1SC", "M2007J3SY", "M2007J3SP",
            "M2007J3SG", "M2007J3SI", "M2007J17G", "M2007J17I", "M2102J2SC", "M2011K2C", "M2011K2G", "M2102K1AC",
            "M2102K1C", "M2102K1G", "M2101K9C", "M2101K9G", "M2101K9R", "M2101K9AG", "M2101K9AI", "2107119DC",
            "2109119DG", "2109119DI", "M2012K11G", "M2012K11AI", "M2012K11I", "21081111RG", "2107113SG", "2107113SI",
            "2107113SR", "21091116I", "21091116UI", "2201123C", "2201123G", "2112123AC", "2112123AG", "2201122C",
            "2201122G", "2207122MC", "2203129G", "2203129I", "2206123SC", "2206122SC", "2203121C", "22071212AG",
            "22081212UG", "22081212R", "A201XM", "2211133C", "2211133G", "2210132C", "2210132G", "2304FPN6DC",
            "2304FPN6DG", "2210129SG", "2306EPN60G", "2306EPN60R", "XIG04", "23078PND5G", "23088PND5R", "A301XM",
            "23127PN0CC", "23127PN0CG", "23116PN5BC", "2311BPN23C", "24031PN0DC", "24030PN60G", "24053PY09I",
            "2406APNFAG", "XIG06", "2407FPN8EG", "2407FPN8ER", "A402XM", "2014616", "2014619", "2014618", "2014617",
            "2015011", "2015021", "2015022", "2015501", "2015211", "2015212", "2015213", "MCE8", "MCT8", "M1910F4G",
            "M1910F4S", "M2002F4LG", "2016080", "MDE5", "MDT5", "MDE5S", "M1803D5XE", "M1803D5XA", "M1803D5XT",
            "M1803D5XC", "M1810E5E", "M1810E5A", "M1810E5GG", "2106118C", "M2011J18C", "22061218C", "2308CPXD0C",
            "24072PX77C", "2405CPX3DC", "2405CPX3DG", "2016001", "2016002", "2016007", "MDE40", "MDT4", "MDI40",
            "M1804E4A", "M1804E4T", "M1804E4C", "M1904F3BC", "M1904F3BT", "M1906F9SC", "M1910F4E", "2109119BC",
            "2109119BC", "2209129SC", "23046PNC9C", "24053PY09C", "M1901F9E", "M1901F9T", "MDG2", "MDI2", "M1804D2SG",
            "M1804D2SI", "M1805D1SG", "M1906F9SH", "M1906F9SI", "A0101", "2015716", "MCE91", "M1806D9W", "M1806D9E",
            "M1806D9PE", "21051182C", "21051182G", "M2105K81AC", "M2105K81C", "22081281AC", "23043RP34C", "23043RP34G",
            "23043RP34I", "23046RP50C", "2307BRPDCC", "24018RPACC", "24018RPACG", "2013022", "2013023", "2013029",
            "2013028", "2014011", "2014501", "2014813", "2014112", "2014811", "2014812", "2014821", "2014817",
            "2014818", "2014819", "2014502", "2014512", "2014816", "2015811", "2015812", "2015810", "2015817",
            "2015818", "2015816", "2016030", "2016031", "2016032", "2016037", "2016036", "2016035", "2016033",
            "2016090", "2016060", "2016111", "2016112", "2016117", "2016116", "MAE136", "MAT136", "MAG138", "MAI132",
            "MDE1", "MDT1", "MDG1", "MDI1", "MEE7", "MET7", "MEG7", "MCE3B", "MCT3B", "MCG3B", "MCI3B", "M1804C3DE",
            "M1804C3DT", "M1804C3DC", "M1804C3DG", "M1804C3DI", "M1805D1SE", "M1805D1ST", "M1805D1SC", "M1805D1SI",
            "M1804C3CE", "M1804C3CT", "M1804C3CC", "M1804C3CG", "M1804C3CI", "M1810F6LE", "M1810F6LT", "M1810F6LG",
            "M1810F6LI", "M1903C3EE", "M1903C3ET", "M1903C3EC", "M1903C3EG", "M1903C3EI", "M1908C3IE", "M1908C3IC",
            "M1908C3IG", "M1908C3II", "M1908C3KE", "M1908C3KG", "M1908C3KI", "M2001C3K3I", "M2004J19C", "M2004J19G",
            "M2004J19I", "M2004J19AG", "M2006C3LC", "M2006C3LG", "M2006C3LVG", "M2006C3LI", "M2006C3LII", "M2006C3MG",
            "M2006C3MT", "M2006C3MNG", "M2006C3MII", "M2010J19SG", "M2010J19SI", "M2010J19SR", "M2010J19ST",
            "M2010J19SY", "M2010J19SL", "21061119AG", "21061119AL", "21061119BI", "21061119DG", "21121119SG",
            "21121119VL", "22011119TI", "22011119UY", "22041219G", "22041219I", "22041219NY", "220333QAG", "220333QBI",
            "220333QNY", "220333QL", "220233L2C", "220233L2G", "220233L2I", "22071219AI", "23053RN02A", "23053RN02I",
            "23053RN02L", "23053RN02Y", "23077RABDC", "23076RN8DY", "23076RA4BR", "XIG03", "A401XM", "23076RN4BI",
            "23076RA4BC", "22120RN86C", "22120RN86G", "22120RN86H", "2212ARNC4L", "22126RN91Y", "2404ARN45A",
            "2404ARN45I", "24049RN28L", "24040RN64Y", "2406ERN9CI", "23106RN0DA", "2311DRN14I", "23100RN82L",
            "23108RN04Y", "23124RN87C", "23124RN87I", "23124RN87G", "2409BRN2CA", "2409BRN2CI", "2409BRN2CL",
            "2409BRN2CY", "2411DRN47C", "2014018", "2013121", "2014017", "2013122", "2014022", "2014021", "2014715",
            "2014712", "2014915", "2014912", "2014916", "2014911", "2014910", "2015052", "2015051", "2015712",
            "2015055", "2015056", "2015617", "2015611", "2015112", "2015116", "2015161", "2016050", "2016051",
            "2016101", "2016130", "2016100", "MBE6A5", "MBT6A5", "MEI7", "MEE7S", "MET7S", "MEC7S", "M1803E7SG",
            "MEI7S", "MDE6", "MDT6", "MDG6", "MDI6", "MDE6S", "MDT6S", "MDG6S", "MDI6S", "M1806E7TG", "M1806E7TI",
            "M1901F7E", "M1901F7T", "M1901F7C", "M1901F7G", "M1901F7I", "M1901F7BE", "M1901F7S", "M1908C3JE",
            "M1908C3JC", "M1908C3JG", "M1908C3JI", "M1908C3XG", "M1908C3JGG", "M1906G7E", "M1906G7T", "M1906G7G",
            "M1906G7I", "M2010J19SC", "M2007J22C", "M2003J15SS", "M2003J15SI", "M2003J15SG", "M2007J22G", "M2007J22R",
            "M2007J17C", "M2003J6A1G", "M2003J6A1R", "M2003J6A1I", "M2003J6B1I", "M2003J6B2G", "M2101K7AG", "M2101K7AI",
            "M2101K7BG", "M2101K7BI", "M2101K7BNY", "M2101K7BL", "M2103K19C", "M2103K19I", "M2103K19G", "M2103K19Y",
            "M2104K19J", "22021119KR", "A101XM", "M2101K6G", "M2101K6T", "M2101K6R", "M2101K6P", "M2101K6I",
            "M2104K10AC", "2109106A1I", "21121119SC", "2201117TG", "2201117TI", "2201117TL", "2201117TY", "21091116AC",
            "21091116AI", "22041219C", "2201117SG", "2201117SI", "2201117SL", "2201117SY", "22087RA4DI", "22031116BG",
            "21091116C", "2201116TG", "2201116TI", "2201116SC", "2201116SG", "2201116SR", "2201116SI", "21091116UC",
            "21091116UG", "22041216C", "22041216UC", "22095RA98C", "23021RAAEG", "23027RAD4I", "23028RA60L",
            "23021RAA2Y", "22101317C", "22111317G", "22111317I", "23076RA4BC", "2303CRA44A", "2303ERA42L", "23030RAC7Y",
            "2209116AG", "22101316C", "22101316G", "22101316I", "22101316UCP", "22101316UG", "22101316UP", "22101316UC",
            "22101320C", "23054RA19C", "23049RAD8C", "23129RAA4G", "23129RA5FL", "23124RA7EO", "2312DRAABC",
            "2312DRAABI", "2312DRAABG", "23117RA68G", "2312DRA50C", "2312DRA50G", "2312DRA50I", "XIG05", "23090RA98C",
            "23090RA98G", "23090RA98I", "24040RA98R", "2406ERN9CC", "2311FRAFDC", "24094RAD4C", "24094RAD4G",
            "24094RAD4I", "24090RA29C", "24090RA29G", "24090RA29I", "24115RA8EC", "24115RA8EG", "24115RA8EI",
            "M2004J7AC", "M2004J7BC", "M2003J15SC", "24069RA21C", "M1903F10A", "M1903F10C", "M1903F10I", "M1903F11A",
            "M1903F11C", "M1903F11I", "M1903F11A", "M2001G7AE", "M2001G7AC", "M2001G7AC", "M1912G7BE", "M1912G7BC",
            "M2001J11C", "M2001J11C", "M2006J10C", "M2007J3SC", "M2012K11AC", "M2012K11C", "M2012K10C", "22021211RC",
            "22041211AC", "22011211C", "21121210C", "22081212C", "22041216I", "23013RK75C", "22127RK46C", "22122RK93C",
            "23078RKD5C", "23113RKC6C", "23117RK66C", "2311DRK48C", "2407FRK8EC", "2016020", "2016021", "M1803E6E",
            "M1803E6T", "M1803E6C", "M1803E6G", "M1803E6I", "M1810F6G", "M1810F6I", "M1903C3GG", "M1903C3GI",
            "220733SG", "220733SH", "220733SL", "220733SFG", "220733SFH", "23028RN4DG", "23028RN4DH", "23026RN54G",
            "23028RNCAG", "23028RNCAH", "23129RN51X", "23129RN51H", "2312CRNCCL", "24048RN6CG", "24048RN6CI",
            "24044RN32L", "2409BRN2CG", "22081283C", "22081283G", "23073RPBFC", "23073RPBFG", "23073RPBFL",
            "2405CRPFDC", "2405CRPFDG", "2405CRPFDI", "2405CRPFDL", "24074RPD2C", "24074RPD2G", "24074RPD2I",
            "24075RP89G", "24076RP19G", "24076RP19I", "M1805E10A", "M2004J11G", "M2012K11AG", "M2104K10I", "22021211RG",
            "22021211RI", "21121210G", "23049PCD8G", "23049PCD8I", "23013PC75G", "24069PC21G", "24069PC21I",
            "23113RKC6G", "M1912G7BI", "M2007J20CI", "M2007J20CG", "M2007J20CT", "M2102J20SG", "M2102J20SI",
            "21061110AG", "2201116PG", "2201116PI", "22041216G", "22041216UG", "22111317PG", "22111317PI", "22101320G",
            "22101320I", "23122PCD1G", "23122PCD1I", "2311DRK48G", "2311DRK48I", "2312FRAFDI", "M2004J19PI",
            "M2003J6CI", "M2010J19CG", "M2010J19CT", "M2010J19CI", "M2103K19PG", "M2103K19PI", "22041219PG",
            "22041219PI", "2201117PG", "2201117PI", "21091116AG", "22031116AI", "22071219CG", "22071219CI",
            "2207117BPG", "2404APC5FG", "2404APC5FI", "23128PC33I", "24066PC95I", "2312FPCA6G", "23076PC4BI",
            "M2006C3MI", "211033MI", "220333QPG", "220333QPI", "220733SPH", "2305EPCC4G", "2302EPCC4H", "22127PC95G",
            "22127PC95H", "2312BPC51X", "2312BPC51H", "2310FPCA4G", "2310FPCA4I", "2405CPCFBG", "24074PCD2I", "FYJ01QP",
            "21051191C"
        ]
        self.all_os_versions = [
            "Android_7.1.2", "Android_8.0.0", "Android_8.1.0", "Android_9.0", "Android_10", "Android_11", "Android_12",
            "Android_13", "Android_6.0.1", "Android_5.1.1", "Android_4.4.4", "Android_4.3", "Android_4.2.2",
            "Android_4.1.2",
        ]
        # 随机生成设备信息
        self.devicetype = random.choice(self.all_device_type)
        self.osversion = random.choice(self.all_os_versions)

        self.cookies = None
        self.recycle_list = None
        self.list = []
        self.total = 0
        self.parent_file_name_list = []
        self.all_file = False
        self.file_page = 0
        self.file_list = []
        self.dir_list = []
        self.name_dict = {}
        if readfile:
            self.read_ini(user_name, pass_word, input_pwd, authorization)
        else:
            if user_name == "" or pass_word == "":
                raise Exception("用户名或密码为空")
            self.user_name = user_name
            self.password = pass_word
            self.authorization = authorization
        self.header_logined = {
            "user-agent": "123pan/v2.4.0(" + self.osversion + ";Xiaomi)",
            "authorization": self.authorization,
            "accept-encoding": "gzip",
            "content-type": "application/json",
            "osversion": self.osversion,
            "loginuuid": str(uuid.uuid4().hex),
            "platform": "android",
            "devicetype": self.devicetype,
            "devicename": "Xiaomi",
            "host": "www.123pan.com",
            "app-version": "61",
            "x-app-version": "2.4.0"
        }
        self.parent_file_id = 0  # 路径，文件夹的id,0为根目录
        self.parent_file_list = [0]
        res_code_getdir = self.get_dir()[0]
        if res_code_getdir != 0:
            self.login()
            self.get_dir()

    def login(self):
        """登录123云盘账户并获取授权令牌"""
        data = {"type": 1, "passport": self.user_name, "password": self.password}
        login_res = requests.post(
            "https://www.123pan.com/b/api/user/sign_in",
            headers=self.header_logined,
            data=data,
        )

        res_sign = login_res.json()
        res_code_login = res_sign["code"]
        if res_code_login != 200:
            logger.error("code = 1 Error:" + str(res_code_login))
            logger.error(res_sign.get("message", ""))
            return res_code_login
        set_cookies = login_res.headers.get("Set-Cookie", "")
        set_cookies_list = {}

        for cookie in set_cookies.split(';'):
            if '=' in cookie:
                key, value = cookie.strip().split('=', 1)
                set_cookies_list[key] = value
            else:
                set_cookies_list[cookie.strip()] = None

        self.cookies = set_cookies_list

        token = res_sign["data"]["token"]
        self.authorization = "Bearer " + token
        self.header_logined["authorization"] = self.authorization
        self.save_file()
        return res_code_login

    def save_file(self):
        """将账户信息保存到配置文件"""
        try:
            config = ConfigManager.load_config()
            config.update({
                "userName": self.user_name,
                "passWord": self.password,
                "authorization": self.authorization,
                "deviceType": self.devicetype,
                "osVersion": self.osversion,
            })
            ConfigManager.save_config(config)
            logger.info("账号已保存")
        except Exception as e:
            logger.error("保存账号失败:", e)

    def get_dir(self, save=True):
        """获取当前目录下的文件列表"""
        return self.get_dir_by_id(self.parent_file_id, save)

    def get_dir_by_id(self, file_id, save=True, all=False, limit=100):
        """按文件夹ID获取文件列表（支持分页）
        
        Args:
            file_id: 文件夹ID
            save: 是否保存结果到列表
            all: 是否强制获取所有文件
            limit: 每页限制数量
        """
        get_pages = 3
        res_code_getdir = 0
        page = self.file_page * get_pages + 1
        lenth_now = len(self.list)
        if all:
            # 强制获取所有文件
            page = 1
            lenth_now = 0
        lists = []

        total = -1
        times = 0
        while (lenth_now < total or total == -1) and (times < get_pages or all):
            base_url = "https://www.123pan.com/api/file/list/new"
            params = {
                "driveId": 0,
                "limit": limit,
                "next": 0,
                "orderBy": "file_id",
                "orderDirection": "desc",
                "parentFileId": str(file_id),
                "trashed": False,
                "SearchData": "",
                "Page": str(page),
                "OnlyLookAbnormalFile": 0,
            }
            try:
                a = requests.get(base_url, headers=self.header_logined, params=params, timeout=30)
            except Exception:
                logger.error("连接失败")
                return -1, []
            text = a.json()
            res_code_getdir = text["code"]
            if res_code_getdir != 0:
                logger.error("code = 2 Error:" + str(res_code_getdir))
                logger.error(text.get("message", ""))
                return res_code_getdir, []
            lists_page = text["data"]["InfoList"]
            lists += lists_page
            total = text["data"]["Total"]
            lenth_now += len(lists_page)
            page += 1
            times += 1
            if times % 5 == 0:
                logger.warning("警告：文件夹内文件过多：" + str(lenth_now) + "/" + str(total))
                logger.info("为防止对服务器造成影响，暂停3秒")
                time.sleep(3)

        if lenth_now < total:
            logger.warning("文件夹内文件过多：" + str(lenth_now) + "/" + str(total))
            self.all_file = False
        else:
            self.all_file = True
        self.total = total
        self.file_page += 1
        if save:
            self.list = self.list + lists

        return res_code_getdir, lists

    def show(self):
        """显示文件列表信息到日志"""
        if not self.all_file:
            logger.info(f"获取了{len(self.list)}/{self.total}个文件")
        else:
            logger.info(f"获取全部{len(self.list)}个文件")

    def link_by_number(self, file_number, showlink=True):
        """按编号获取文件下载链接"""
        file_detail = self.list[file_number]
        return self.link_by_fileDetail(file_detail, showlink)

    def link_by_fileDetail(self, file_detail, showlink=True):
        """按文件详情获取下载链接"""
        type_detail = file_detail["Type"]

        if type_detail == 1:
            down_request_url = "https://www.123pan.com/a/api/file/batch_download_info"
            down_request_data = {"fileIdList": [{"fileId": int(file_detail["FileId"])}]}

        else:
            down_request_url = "https://www.123pan.com/a/api/file/download_info"
            down_request_data = {
                "driveId": 0,
                "etag": file_detail["Etag"],
                "fileId": file_detail["FileId"],
                "s3keyFlag": file_detail["S3KeyFlag"],
                "type": file_detail["Type"],
                "fileName": file_detail["FileName"],
                "size": file_detail["Size"],
            }

        link_res = requests.post(
            down_request_url,
            headers=self.header_logined,
            data=json.dumps(down_request_data),
            timeout=10
        )
        link_res_json = link_res.json()
        res_code_download = link_res_json["code"]
        if res_code_download != 0:
            logger.error("获取下载链接失败，返回码: " + str(res_code_download))
            logger.error(link_res_json.get("message", ""))
            return res_code_download
        down_load_url = link_res.json()["data"]["DownloadUrl"]
        next_to_get = requests.get(down_load_url, timeout=10, allow_redirects=False).text
        url_pattern = re.compile(r"href='(https?://[^']+)'")
        redirect_url = url_pattern.findall(next_to_get)[0]
        if showlink:
            logger.info(f"获取下载链接成功: {redirect_url}")

        return redirect_url

    def download(self, file_number, download_path="download"):
        """下载文件"""
        file_detail = self.list[file_number]
        if file_detail["Type"] == 1:
            logger.info("开始下载")
            file_name = file_detail["FileName"] + ".zip"
        else:
            file_name = file_detail["FileName"]  # 文件名

        down_load_url = self.link_by_number(file_number, showlink=False)
        if type(down_load_url) == int:
            return
        self.download_from_url(down_load_url, file_name, download_path)

    def download_from_url(self, url, file_name, download_path="download"):
        """从URL下载文件"""
        if not os.path.exists(download_path):
            logger.info("创建下载目录")
            os.makedirs(download_path)
        
        file_path = os.path.join(download_path, file_name)
        temp_path = file_path + ".123pan"
        
        # 如果临时文件存在，删除它（防止之前的不完整下载）
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        down = requests.get(url, stream=True, timeout=10)
        file_size = int(down.headers.get("Content-Length", 0) or 0)
        
        # 以.123pan后缀下载，下载完成重命名，防止下载中断
        with open(temp_path, "wb") as f:
            for chunk in down.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        os.rename(temp_path, file_path)

    def get_all_things(self, id):
        """获取文件夹内所有内容"""
        self.dir_list.remove(id)
        all_list = self.get_dir_by_id(id, save=False)[1]

        for i in all_list:
            if i["Type"] == 0:
                self.file_list.append(i)
            else:
                self.dir_list.append(i["FileId"])
                self.name_dict[i["FileId"]] = i["FileName"]

        for i in self.dir_list:
            self.get_all_things(i)

    def download_dir(self, file_detail, download_path_root="download"):
        """下载文件夹"""
        self.name_dict[file_detail["FileId"]] = file_detail["FileName"]
        if file_detail["Type"] != 1:
            logger.warning("不是文件夹")
            return

        all_list = self.get_dir_by_id(file_detail["FileId"], save=False, all=True, limit=100)[1]
        for i in all_list[::-1]:
            if i["Type"] == 0:  # 直接开始下载
                AbsPath = i["AbsPath"]
                for key, value in self.name_dict.items():
                    AbsPath = AbsPath.replace(str(key), value)
                download_path = download_path_root + AbsPath
                download_path = download_path.replace("/" + str(i["FileId"]), "")
                self.download_from_url(i["DownloadUrl"], i["FileName"], download_path)

            else:
                self.download_dir(i, download_path_root)

    def recycle(self):
        """获取回收站列表"""
        recycle_id = 0
        url = (
                "https://www.123pan.com/a/api/file/list/new?driveId=0&limit=100&next=0"
                "&orderBy=fileId&orderDirection=desc&parentFileId="
                + str(recycle_id)
                + "&trashed=true&&Page=1"
        )
        recycle_res = requests.get(url, headers=self.header_logined, timeout=10)
        json_recycle = recycle_res.json()
        recycle_list = json_recycle["data"]["InfoList"]
        self.recycle_list = recycle_list

    def delete_file(self, file, by_num=True, operation=True):
        """删除或恢复文件"""
        if by_num:
            if not str(file).isdigit():
                raise ValueError("文件索引必须是数字")
            if 0 <= file < len(self.list):
                file_detail = self.list[file]
            else:
                raise IndexError("文件索引超出范围")
        else:
            if file in self.list:
                file_detail = file
            else:
                raise ValueError("文件不存在")
        data_delete = {
            "driveId": 0,
            "fileTrashInfoList": file_detail,
            "operation": operation,
        }
        delete_res = requests.post(
            "https://www.123pan.com/a/api/file/trash",
            data=json.dumps(data_delete),
            headers=self.header_logined,
            timeout=10
        )
        dele_json = delete_res.json()
        print(dele_json)
        message = dele_json.get("message", "")
        print(message)

    def share(self, file_id_list, share_pwd=""):
        """分享文件"""
        if not file_id_list:
            raise ValueError("文件ID列表为空")
        data = {
            "driveId": 0,
            "expiration": "2099-12-12T08:00:00+08:00",
            "fileIdList": file_id_list,
            "shareName": "123云盘分享",
            "sharePwd": share_pwd or "",
            "event": "shareCreate"
        }
        share_res = requests.post(
            "https://www.123pan.com/a/api/share/create",
            headers=self.header_logined,
            data=json.dumps(data),
            timeout=10
        )
        share_res_json = share_res.json()
        if share_res_json.get("code", -1) != 0:
            raise RuntimeError(f"分享失败: {share_res_json.get('message', '')}")
        share_key = share_res_json["data"]["ShareKey"]
        share_url = "https://www.123pan.com/s/" + share_key
        return share_url

    def up_load(self, file_path):
        """上传文件"""
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_name = os.path.basename(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError("文件不存在")
        if os.path.isdir(file_path):
            raise IsADirectoryError("不支持文件夹上传")
        fsize = os.path.getsize(file_path)
        readable_hash = self._compute_file_md5(file_path)

        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": self.parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }

        up_res = requests.post(
            "https://www.123pan.com/b/api/file/upload_request",
            headers=self.header_logined,
            data=list_up_request,
            timeout=10
        )
        up_res_json = up_res.json()
        res_code_up = up_res_json.get("code", -1)
        if res_code_up == 5060:
            # 同名文件处理由调用者在GUI中处理
            raise RuntimeError("同名文件存在")
        if res_code_up != 0:
            raise RuntimeError(f"上传请求失败: {up_res_json}")
        up_file_id = up_res_json["data"]["FileId"]
        if up_res_json["data"].get("Reuse", False):
            return up_file_id

        bucket = up_res_json["data"]["Bucket"]
        storage_node = up_res_json["data"]["StorageNode"]
        upload_key = up_res_json["data"]["Key"]
        upload_id = up_res_json["data"]["UploadId"]
        up_file_id = up_res_json["data"]["FileId"]  # 上传文件的fileId,完成上传后需要用到

        # 获取已将上传的分块
        start_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        start_res = requests.post(
            "https://www.123pan.com/b/api/file/s3_list_upload_parts",
            headers=self.header_logined,
            data=json.dumps(start_data),
            timeout=10
        )
        start_res_json = start_res.json()
        res_code_up = start_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"获取传输列表失败: {start_res_json}")

        # 分块，每一块取一次链接，依次上传
        block_size = 5242880
        with open(file_path, "rb") as f:
            part_number_start = 1
            put_size = 0
            while True:
                data = f.read(block_size)
                put_size = put_size + len(data)

                if not data:
                    break
                get_link_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "partNumberEnd": part_number_start + 1,
                    "partNumberStart": part_number_start,
                    "uploadId": upload_id,
                    "StorageNode": storage_node,
                }

                get_link_url = (
                    "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch"
                )
                get_link_res = requests.post(
                    get_link_url,
                    headers=self.header_logined,
                    data=json.dumps(get_link_data),
                    timeout=10
                )
                get_link_res_json = get_link_res.json()
                res_code_up = get_link_res_json.get("code", -1)
                if res_code_up != 0:
                    raise RuntimeError(f"获取链接失败: {get_link_res_json}")
                upload_url = get_link_res_json["data"]["presignedUrls"][
                    str(part_number_start)
                ]
                requests.put(upload_url, data=data, timeout=10)

                part_number_start = part_number_start + 1


        uploaded_list_url = "https://www.123pan.com/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {
            "bucket": bucket,
            "key": upload_key,
            "uploadId": upload_id,
            "storageNode": storage_node,
        }
        requests.post(
            uploaded_list_url,
            headers=self.header_logined,
            data=json.dumps(uploaded_comp_data),
            timeout=10
        )
        compmultipart_up_url = (
            "https://www.123pan.com/b/api/file/s3_complete_multipart_upload"
        )
        requests.post(
            compmultipart_up_url,
            headers=self.header_logined,
            data=json.dumps(uploaded_comp_data),
            timeout=10
        )

        if fsize > 64 * 1024 * 1024:
            time.sleep(3)
        close_up_session_url = "https://www.123pan.com/b/api/file/upload_complete"
        close_up_session_data = {"fileId": up_file_id}
        close_up_session_res = requests.post(
            close_up_session_url,
            headers=self.header_logined,
            data=json.dumps(close_up_session_data),
            timeout=10
        )
        close_res_json = close_up_session_res.json()
        res_code_up = close_res_json.get("code", -1)
        if res_code_up != 0:
            raise RuntimeError(f"上传完成确认失败: {close_res_json}")
        return up_file_id

    def cd(self, dir_num):
        """进入文件夹"""
        if dir_num == "..":
            if len(self.parent_file_list) > 1:
                self.all_file = False
                self.file_page = 0
                self.parent_file_list.pop()
                self.parent_file_id = self.parent_file_list[-1]
                self.list = []
                self.parent_file_name_list.pop()
                self.get_dir()
            else:
                raise RuntimeError("已经是根目录")
            return
        if dir_num == "/":
            self.all_file = False
            self.file_page = 0
            self.parent_file_id = 0
            self.parent_file_list = [0]
            self.list = []
            self.parent_file_name_list = []
            self.get_dir()
            return
        if not str(dir_num).isdigit():
            raise ValueError("文件夹编号必须是数字")
        dir_num = int(dir_num) - 1
        if dir_num > (len(self.list) - 1) or dir_num < 0:
            raise IndexError("文件夹编号超出范围")
        if self.list[dir_num]["Type"] != 1:
            raise TypeError("选中项不是文件夹")
        self.all_file = False
        self.file_page = 0
        self.parent_file_id = self.list[dir_num]["FileId"]
        self.parent_file_list.append(self.parent_file_id)
        self.parent_file_name_list.append(self.list[dir_num]["FileName"])
        self.list = []
        self.get_dir()

    def cdById(self, file_id):
        """按ID进入文件夹"""
        self.all_file = False
        self.file_page = 0
        self.list = []
        self.parent_file_id = file_id
        self.parent_file_list.append(self.parent_file_id)
        self.get_dir()
        self.show()

    def read_ini(
            self,
            user_name,
            pass_word,
            input_pwd,
            authorization="",
    ):
        """从配置文件读取账号信息"""
        try:
            config = ConfigManager.load_config()
            deviceType = config.get("deviceType", "")
            osVersion = config.get("osVersion", "")
            if deviceType:
                self.devicetype = deviceType
            if osVersion:
                self.osversion = osVersion
            user_name = config.get("userName", user_name)
            pass_word = config.get("passWord", pass_word)
            authorization = config.get("authorization", authorization)
        except Exception as e:
            logger.error(f"获取配置失败: {e}")
            if user_name == "" or pass_word == "":
                raise Exception("无法从配置获取账号信息")

        self.user_name = user_name
        self.password = pass_word
        self.authorization = authorization

    def mkdir(self, dirname, remakedir=False):
        """创建文件夹"""
        if not remakedir:
            for i in self.list:
                if i["FileName"] == dirname:
                    logger.info("文件夹已存在")
                    return i["FileId"]

        url = "https://www.123pan.com/a/api/file/upload_request"
        data_mk = {
            "driveId": 0,
            "etag": "",
            "fileName": dirname,
            "parentFileId": self.parent_file_id,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        res_mk = requests.post(
            url,
            headers=self.header_logined,
            data=json.dumps(data_mk),
            timeout=10
        )
        try:
            res_json = res_mk.json()
        except json.decoder.JSONDecodeError:
            logger.error("创建失败")
            logger.error(res_mk.text)
            return
        code_mkdir = res_json.get("code", -1)

        if code_mkdir == 0:
            logger.info(f"创建成功: {res_json['data']['FileId']}")
            self.get_dir()
            return res_json["data"]["Info"]["FileId"]
        logger.error(f"创建失败: {res_json}")
        return
    
    @staticmethod
    def _compute_file_md5(file_path):
        """计算文件MD5值"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
        return md5.hexdigest()

    def stream_download_by_number(self, file_number, download_dir, task_id=None, signals=None, task=None):
        file_detail = self.list[file_number]
        if file_detail["Type"] == 1:
            redirect_url = self.link_by_fileDetail(file_detail, showlink=False)
        else:
            redirect_url = self.link_by_number(file_number, showlink=False)
        if isinstance(redirect_url, int):
            raise RuntimeError("获取下载链接失败，返回码: " + str(redirect_url))
        if file_detail["Type"] == 1:
            fname = file_detail["FileName"] + ".zip"
        else:
            fname = file_detail["FileName"]

        out_path = os.path.join(download_dir, fname)
        temp = out_path + ".123pan"

        os.makedirs(download_dir, exist_ok=True)

        if os.path.exists(out_path):
            # 由调用者决定覆盖行为
            raise FileExistsError(out_path)

        total = 0
        accept_ranges = False
        try:
            head = requests.head(redirect_url, allow_redirects=True, timeout=30)
            head.raise_for_status()
            total = int(head.headers.get("Content-Length", 0) or 0)
            accept_ranges = head.headers.get("Accept-Ranges", "").lower() == "bytes"
        except Exception:
            try:
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0) or 0)
                    accept_ranges = r.headers.get("Accept-Ranges", "").lower() == "bytes"
            except Exception:
                total = 0
                accept_ranges = False

        try:
            if accept_ranges and total and total > 1024 * 1024 * 2:
                num_threads = min(8, max(1, int(total / (5 * 1024 * 1024))))
                part_size = total // num_threads
                downloaded = [0]
                dl_lock = threading.Lock()

                def download_range(start, end, index):
                    part_path = f"{temp}.part{index}"
                    headers = {"Range": f"bytes={start}-{end}"}
                    try:
                        with requests.get(redirect_url, headers=headers, stream=True, timeout=30) as r:
                            r.raise_for_status()
                            with open(part_path, "wb") as pf:
                                for chunk in r.iter_content(chunk_size=8192):
                                    if task:
                                        try:
                                            task._pause_event.wait()
                                        except Exception:
                                            pass
                                        if task.is_cancelled:
                                            return False
                                    if chunk:
                                        pf.write(chunk)
                                        with dl_lock:
                                            downloaded[0] += len(chunk)
                                            if total and signals:
                                                signals.progress.emit(int(downloaded[0] * 100 / total))
                        return True
                    except Exception:
                        if os.path.exists(part_path):
                            try:
                                os.remove(part_path)
                            except Exception:
                                pass
                        return False

                futures = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as exe:
                    for i in range(num_threads):
                        start = i * part_size
                        end = (start + part_size - 1) if i < num_threads - 1 else (total - 1)
                        futures.append(exe.submit(download_range, start, end, i))

                    ok = True
                    for f in concurrent.futures.as_completed(futures):
                        if not f.result():
                            ok = False
                            break

                if not ok:
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    raise RuntimeError("分片下载失败")
                if task and task.is_cancelled:
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    return "已取消"

                with open(temp, "wb") as out_f:
                    for i in range(num_threads):
                        p = f"{temp}.part{i}"
                        with open(p, "rb") as pf:
                            while True:
                                chunk = pf.read(8192)
                                if not chunk:
                                    break
                                out_f.write(chunk)
                        try:
                            os.remove(p)
                        except Exception:
                            pass

                if task and task.is_cancelled:
                    if os.path.exists(temp):
                        os.remove(temp)
                    return "已取消"
                os.replace(temp, out_path)
                return out_path
            else:
                with requests.get(redirect_url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    done = 0
                    with open(temp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if task:
                                try:
                                    task._pause_event.wait()
                                except Exception:
                                    pass
                                if task.is_cancelled:
                                    f.close()
                                    if os.path.exists(temp):
                                        os.remove(temp)
                                    return "已取消"
                            if chunk:
                                f.write(chunk)
                                done += len(chunk)
                                if total and signals:
                                    signals.progress.emit(int(done * 100 / total))
                if task and task.is_cancelled:
                    if os.path.exists(temp):
                        os.remove(temp)
                    return "已取消"
                os.replace(temp, out_path)
                return out_path
        except Exception:
            if os.path.exists(temp):
                try:
                    os.remove(temp)
                except Exception:
                    pass
            raise

    def upload_file_stream(self, file_path, dup_choice=1, task_id=None, signals=None, task=None):
        """上传文件（分块），支持 progress 回调 与 取消/暂停 控制。

        与 MainWindow 的 ThreadedTask 接口兼容。
        """
        file_path = file_path.replace('"', "").replace("\\", "/")
        file_name = os.path.basename(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError("文件不存在")
        if os.path.isdir(file_path):
            raise IsADirectoryError("不支持文件夹上传")
        fsize = os.path.getsize(file_path)

        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            while True:
                data = f.read(64 * 1024)
                if not data:
                    break
                md5.update(data)
                if task and task.is_cancelled:
                    return "已取消"
        readable_hash = md5.hexdigest()

        list_up_request = {
            "driveId": 0,
            "etag": readable_hash,
            "fileName": file_name,
            "parentFileId": self.parent_file_id,
            "size": fsize,
            "type": 0,
            "duplicate": 0,
        }
        url = "https://www.123pan.com/b/api/file/upload_request"
        headers = self.header_logined.copy()
        res = requests.post(url, headers=headers, data=list_up_request, timeout=30)
        res_json = res.json()
        code = res_json.get("code", -1)
        if code == 5060:
            list_up_request["duplicate"] = dup_choice
            res = requests.post(url, headers=headers, data=json.dumps(list_up_request), timeout=30)
            res_json = res.json()
            code = res_json.get("code", -1)
        if code != 0:
            raise RuntimeError("上传请求失败: " + json.dumps(res_json, ensure_ascii=False))
        data = res_json["data"]
        if data.get("Reuse"):
            return "复用上传成功"
        bucket = data["Bucket"]
        storage_node = data["StorageNode"]
        upload_key = data["Key"]
        upload_id = data["UploadId"]
        up_file_id = data["FileId"]
        block_size = 5242880
        total_sent = 0
        part_number = 1
        with open(file_path, "rb") as f:
            while True:
                block = f.read(block_size)
                if not block:
                    break
                get_link_data = {
                    "bucket": bucket,
                    "key": upload_key,
                    "partNumberEnd": part_number + 1,
                    "partNumberStart": part_number,
                    "uploadId": upload_id,
                    "StorageNode": storage_node,
                }
                get_link_url = "https://www.123pan.com/b/api/file/s3_repare_upload_parts_batch"
                get_link_res = requests.post(get_link_url, headers=headers, data=json.dumps(get_link_data), timeout=30)
                get_link_res_json = get_link_res.json()
                if get_link_res_json.get("code", -1) != 0:
                    raise RuntimeError("获取上传链接失败: " + json.dumps(get_link_res_json, ensure_ascii=False))
                upload_url = get_link_res_json["data"]["presignedUrls"][str(part_number)]
                requests.put(upload_url, data=block, timeout=60)
                total_sent += len(block)
                if signals and fsize:
                    signals.progress.emit(int(total_sent * 100 / fsize))
                part_number += 1
        uploaded_list_url = "https://www.123pan.com/b/api/file/s3_list_upload_parts"
        uploaded_comp_data = {"bucket": bucket, "key": upload_key, "uploadId": upload_id, "storageNode": storage_node}
        requests.post(uploaded_list_url, headers=headers, data=json.dumps(uploaded_comp_data), timeout=30)
        compmultipart_up_url = "https://www.123pan.com/b/api/file/s3_complete_multipart_upload"
        requests.post(compmultipart_up_url, headers=headers, data=json.dumps(uploaded_comp_data), timeout=30)
        if fsize > 64 * 1024 * 1024:
            time.sleep(3)
        close_up_session_url = "https://www.123pan.com/b/api/file/upload_complete"
        close_up_session_data = {"fileId": up_file_id}
        close_res = requests.post(close_up_session_url, headers=headers, data=json.dumps(close_up_session_data), timeout=30)
        cr = close_res.json()
        if cr.get("code", -1) != 0:
            raise RuntimeError("上传完成确认失败: " + json.dumps(cr, ensure_ascii=False))
        return up_file_id


# ==================== 工具函数和任务管理模块 ====================

def format_file_size(size):
    """格式化文件大小"""
    if size > 1073741824:
        return f"{round(size / 1073741824, 2)} GB"
    elif size > 1048576:
        return f"{round(size / 1048576, 2)} MB"
    elif size > 1024:
        return f"{round(size / 1024, 2)} KB"
    else:
        return f"{size} B"


class TransferTask:
    """传输任务的数据模型"""
    def __init__(self, task_id, task_type, name, size):
        self.id = task_id
        self.type = task_type  # "上传" 或 "下载"
        self.name = name
        self.size = size
        self.progress = 0
        self.status = "等待中"
        self.file_path = None
        self.threaded_task = None
        self.is_paused = False

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "size": self.size,
            "progress": self.progress,
            "status": self.status,
            "file_path": self.file_path
        }


class TransferTaskManager:
    """传输任务管理器 - 仅处理业务逻辑，不涉及UI"""
    def __init__(self):
        self.tasks = {}
        self.next_task_id = 0
        self.lock = threading.Lock()

    def create_task(self, task_type, name, size):
        """创建新任务并返回task_id"""
        with self.lock:
            task_id = self.next_task_id
            self.next_task_id += 1
            self.tasks[task_id] = TransferTask(task_id, task_type, name, size)
        return task_id

    def get_task(self, task_id):
        """获取指定任务"""
        return self.tasks.get(task_id)

    def update_task_progress(self, task_id, progress):
        """更新任务进度"""
        task = self.get_task(task_id)
        if task:
            task.progress = max(0, min(100, progress))

    def update_task_status(self, task_id, status):
        """更新任务状态"""
        task = self.get_task(task_id)
        if task:
            task.status = status

    def update_task(self, task_id, progress=None, status=None):
        """更新任务（进度和/或状态）"""
        task = self.get_task(task_id)
        if task:
            if progress is not None:
                task.progress = max(0, min(100, progress))
            if status is not None:
                task.status = status

    def cancel_task(self, task_id):
        """取消任务"""
        task = self.get_task(task_id)
        if task:
            task.status = "已取消"
            if task.threaded_task:
                try:
                    task.threaded_task.cancel()
                except:
                    pass
            return True
        return False

    def pause_task(self, task_id):
        """暂停任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.pause()
                task.status = "已暂停"
                task.is_paused = True
                return True
            except:
                pass
        return False

    def resume_task(self, task_id):
        """恢复任务"""
        task = self.get_task(task_id)
        if task and task.threaded_task:
            try:
                task.threaded_task.resume()
                task.status = "下载中" if task.type == "下载" else "上传中"
                task.is_paused = False
                return True
            except:
                pass
        return False

    def remove_task(self, task_id):
        """移除任务"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            return True
        return False

    def get_all_tasks(self):
        """获取所有任务"""
        return list(self.tasks.values())

    def clear_completed_tasks(self):
        """清除已完成的任务"""
        to_remove = [task_id for task_id, task in self.tasks.items() 
                     if task.status in ("已完成", "已取消", "失败")]
        for task_id in to_remove:
            del self.tasks[task_id]


class FileDataManager:
    """文件数据处理器 - 处理与文件相关的业务逻辑，不涉及UI"""
    
    @staticmethod
    def get_file_type_name(file_type):
        """根据文件类型返回类型名称"""
        return "文件夹" if file_type == 1 else "文件"

    @staticmethod
    def format_file_size_value(size):
        """格式化文件大小（工具函数别名）"""
        return format_file_size(size)

    @staticmethod
    def get_file_extension(filename):
        """获取文件扩展名"""
        return os.path.splitext(filename)[1].lower()

    @staticmethod
    def validate_file_exists(file_path):
        """验证文件是否存在"""
        return os.path.isfile(file_path)

    @staticmethod
    def is_duplicate_filename(pan_instance, filename):
        """检查是否存在同名文件"""
        return any(item.get("FileName") == filename for item in pan_instance.list)
