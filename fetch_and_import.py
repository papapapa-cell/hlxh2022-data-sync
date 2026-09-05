# -*- coding: utf-8 -*-
"""
欢乐星会影院 - 云端每日数据自动抓取+写入飞书多维表格
运行环境：GitHub Actions / 云函数（无需本地电脑）
依赖：requests
配置：全部通过环境变量注入（GitHub Secrets / 云函数环境变量）
"""
import os
import sys
import json
import time
import datetime
import requests

# ============ 配置（从环境变量读取） ============
HLXH_USERNAME = os.environ.get("HLXH_USERNAME", "")
HLXH_PASSWORD = os.environ.get("HLXH_PASSWORD", "")
HLXH_API_BASE = os.environ.get("HLXH_API_BASE", "https://huanlexinghui.tonul.cn/admin")
HLXH_FIXED_TOKEN = os.environ.get("HLXH_FIXED_TOKEN", "7aeeb7da08390a43f73f97e3bc319c79")
HLXH_ORG_ID = int(os.environ.get("HLXH_ORG_ID", "1"))

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_BASE_TOKEN = os.environ.get("FEISHU_BASE_TOKEN", "WSuibMYUIaGZIhs8VpecRHIsnYz")
FEISHU_COUPON_TABLE_ID = os.environ.get("FEISHU_COUPON_TABLE_ID", "tblzps9oCrEvTL76")
FEISHU_SUMMARY_TABLE_ID = os.environ.get("FEISHU_SUMMARY_TABLE_ID", "tblZjHqa6HzLsyNR")

BATCH_SIZE = 200  # 飞书批量创建单批上限 1000，取 200 更稳

# 时区（北京时间）
CN_TZ = datetime.timezone(datetime.timedelta(hours=8))


# ============ 时间工具 ============
def ts_to_ms(ts):
    """秒级时间戳 -> 毫秒（供飞书 datetime 字段）"""
    if ts is None or ts == 0:
        return None
    try:
        return int(ts) * 1000
    except Exception:
        return None


def ts_to_date_str(ts):
    if ts is None or ts == 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(ts, tz=CN_TZ).strftime("%Y-%m-%d")
    except Exception:
        return None


def ts_to_dt_str(ts):
    if ts is None or ts == 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(ts, tz=CN_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def extract_seat(t):
    seats = []
    vos = t.get("cinemaSeatsJsonVOS") or []
    if vos:
        for s in vos:
            if isinstance(s, dict):
                row = s.get("rowNum") or s.get("rowId")
                col = s.get("colNum") or s.get("colId")
                if row and col:
                    seats.append(f"{row}排{col}座")
                elif s.get("seatCode"):
                    seats.append(s["seatCode"])
    if not seats:
        si = t.get("seatInfo")
        if isinstance(si, dict):
            row = si.get("rowNum") or si.get("rowId")
            col = si.get("colNum") or si.get("colId")
            if row and col:
                seats.append(f"{row}排{col}座")
    return ";".join(seats) if seats else None


PAY_TYPE_MAP = {0: None, 1: "微信支付", 2: "支付宝", 3: "会员卡支付", 4: "现金", 5: "银行卡"}


# ============ 数据转换（输出飞书 OpenAPI CellValue） ============
def ticket_to_cell(t):
    """转换影票记录为飞书 OpenAPI 字段格式"""
    rec = {}
    d = ts_to_date_str(t.get("showStartTime"))
    if d:
        rec["放映日期"] = ts_to_ms(t.get("showStartTime"))
        try:
            dt = datetime.datetime.strptime(d, "%Y-%m-%d")
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            rec["星期"] = weekdays[dt.weekday()]
        except Exception:
            pass
    if t.get("cinemaName"):
        rec["所属影院"] = t["cinemaName"]
    if t.get("orderNo"):
        rec["订单编号"] = t["orderNo"]
    if t.get("outTradeNo"):
        rec["商户流水号"] = t["outTradeNo"]
    if t.get("source") is not None:
        rec["订单来源"] = str(t["source"])
    seat = extract_seat(t)
    if seat:
        rec["座位"] = seat
    if t.get("price") is not None:
        rec["座位价格(元)"] = float(t["price"])
    if t.get("payment") is not None:
        rec["实付金额(元)"] = float(t["payment"])
    if t.get("ticketPrice") is not None:
        rec["发行价格(元)"] = float(t["ticketPrice"])
    pay = PAY_TYPE_MAP.get(t.get("payType"))
    if pay:
        rec["支付方式"] = pay
    if t.get("cardNumber"):
        rec["卡号"] = t["cardNumber"]
    if t.get("tripartitePlatform") is not None:
        rec["第三方平台"] = str(t["tripartitePlatform"])
    if t.get("couponPriceTotal") is not None:
        rec["兑换券价格"] = float(t["couponPriceTotal"])
    if t.get("filmName"):
        rec["影片信息"] = t["filmName"]
    if t.get("hallName"):
        rec["影厅"] = t["hallName"]
    st = ts_to_dt_str(t.get("showStartTime"))
    if st:
        rec["放映起始时间"] = ts_to_ms(t.get("showStartTime"))
    et = ts_to_dt_str(t.get("showEndTime"))
    if et:
        rec["放映结束时间"] = ts_to_ms(t.get("showEndTime"))
    if t.get("nickname"):
        rec["用户昵称"] = t["nickname"]
    if t.get("phone"):
        rec["会员手机号"] = t["phone"]
    if t.get("pcCreateUserName"):
        rec["后台出票人"] = t["pcCreateUserName"]
    if t.get("buyTicketMode") is not None:
        rec["购票模式"] = str(t["buyTicketMode"])
    ts_status = t.get("ticketStatus")
    if ts_status == 1:
        rec["取票状态"] = "已取票"
    elif ts_status == 0:
        rec["取票状态"] = "未取票"
    if t.get("printTime"):
        rec["取票时间"] = ts_to_ms(t.get("printTime"))
    if t.get("barcode"):
        rec["取票号"] = t["barcode"]
    elif t.get("barcodes"):
        rec["取票号"] = t["barcodes"]
    if t.get("createTime"):
        rec["销售时间"] = ts_to_ms(t.get("createTime"))
    is_refund = (t.get("status") == "AFTERSALE_FINISH") or (t.get("refundTime") is not None)
    rec["退票信息"] = "已退票" if is_refund else "未退票"
    if t.get("status"):
        rec["订单状态"] = t["status"]
    if t.get("refundTime"):
        rec["退票时间"] = ts_to_ms(t.get("refundTime"))
    if t.get("serviceFee") is not None:
        rec["服务费"] = float(t["serviceFee"])
    return rec


def coupon_to_cell(c):
    """转换兑换券记录为飞书 OpenAPI 字段格式"""
    rec = {}
    if c.get("grantCinemaName"):
        rec["发券影院"] = c["grantCinemaName"]
    if c.get("cinemaName"):
        rec["消费影院"] = c["cinemaName"]
    if c.get("source") is not None:
        rec["订单来源"] = str(c["source"])
    if c.get("orderNo"):
        rec["订单编号"] = c["orderNo"]
    if c.get("outTradeNo"):
        rec["支付编号"] = c["outTradeNo"]
    if c.get("barcode"):
        rec["券号"] = c["barcode"]
    if c.get("nickname"):
        rec["会员昵称"] = c["nickname"]
    if c.get("memberPhone"):
        rec["会员手机号"] = c["memberPhone"]
    if c.get("filmName"):
        rec["影片名称"] = c["filmName"]
    if c.get("hallName"):
        rec["影厅名称"] = c["hallName"]
    if c.get("seats"):
        rec["座位"] = c["seats"]
    if c.get("totalFee") is not None:
        rec["消费总额"] = float(c["totalFee"])
    if c.get("seatPrice") is not None:
        rec["座位价格"] = float(c["seatPrice"])
    if c.get("showStartTime"):
        rec["放映起始时间"] = ts_to_ms(c.get("showStartTime"))
    if c.get("showEndTime"):
        rec["放映结束时间"] = ts_to_ms(c.get("showEndTime"))
    if c.get("createTime"):
        rec["兑换时间"] = ts_to_ms(c.get("createTime"))
    if c.get("cardNumber"):
        rec["卡号"] = c["cardNumber"]
    if c.get("balanceConsume") is not None:
        rec["余额消费"] = float(c["balanceConsume"])
    return rec


# ============ 欢乐星后台抓取 ============
class HLXHClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://huanlexinghui.tonul.cn/dashboard/login",
            "Origin": "https://huanlexinghui.tonul.cn",
        })
        self.session_key = ""

    def _common_params(self):
        return {
            "apiVersions": "v1",
            "appVersion": "0.0.0",
            "deviceCode": "developer",
            "platform": "0",
            "sessionKey": self.session_key,
            "timestamp": str(int(time.time())),
            "token": HLXH_FIXED_TOKEN,
            "source": "1",
        }

    def login(self):
        params = self._common_params()
        params["data"] = json.dumps({"username": HLXH_USERNAME, "password": HLXH_PASSWORD}, ensure_ascii=False)
        resp = self.session.post(f"{HLXH_API_BASE}/account/login.do", data=params, timeout=30)
        result = resp.json()
        if result.get("code") != 200:
            raise RuntimeError(f"登录失败: {result.get('message')}")
        self.session_key = self.session.cookies.get_dict().get("sessionKey", "")
        if not self.session_key:
            raise RuntimeError("登录成功但未获取到 sessionKey")
        print(f"[HLXH] 登录成功 sessionKey={self.session_key[:8]}...")

    def _call(self, api_path, biz_data):
        params = self._common_params()
        params["data"] = json.dumps(biz_data, ensure_ascii=False)
        resp = self.session.post(f"{HLXH_API_BASE}{api_path}", data=params, timeout=60)
        result = resp.json()
        if result.get("code") not in (0, 200):
            raise RuntimeError(f"API {api_path} 失败: {result.get('message')}")
        return result.get("data", {})

    def fetch_tickets(self, start_ts, end_ts):
        all_data, page, page_size = [], 1, 1000
        while True:
            biz = {
                "page": page, "pageSize": page_size, "ticketStatus": "",
                "organizationId": HLXH_ORG_ID,
                "showStartTime": start_ts, "showEndTime": end_ts,
            }
            data = self._call("/orderBase/ticketOrderSeatList.do", biz)
            rows = data.get("list") or []
            if not rows:
                break
            all_data.extend(rows)
            total = data.get("totalCount") or 0
            if len(all_data) >= total or len(rows) < page_size:
                break
            page += 1
            time.sleep(0.5)
        return all_data

    def fetch_coupons(self, start_ts=None, end_ts=None):
        all_data, page, page_size = [], 1, 1000
        while True:
            biz = {"page": page, "pageSize": page_size, "organizationId": HLXH_ORG_ID, "grantCinemaId": ""}
            if start_ts is not None:
                biz["startTime"] = start_ts
            if end_ts is not None:
                biz["endTime"] = end_ts
            data = self._call("/cardConsume/statement.do", biz)
            rows = data.get("list") or []
            if not rows:
                break
            all_data.extend(rows)
            total = data.get("totalCount") or 0
            if len(all_data) >= total or len(rows) < page_size:
                break
            page += 1
            time.sleep(0.3)
        return all_data


# ============ 飞书 OpenAPI ============
class FeishuClient:
    def __init__(self):
        self.base = "https://open.feishu.cn/open-apis"
        self.tenant_token = ""
        if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
            raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量")

    def get_tenant_token(self):
        resp = requests.post(
            f"{self.base}/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=30,
        )
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {result.get('msg')}")
        self.tenant_token = result["tenant_access_token"]
        print("[Feishu] 已获取 tenant_access_token")

    def _headers(self):
        return {"Authorization": f"Bearer {self.tenant_token}"}

    def list_tables(self):
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables"
        params = {"page_size": 100}
        tables = {}
        has_more, page_token = True, ""
        while has_more:
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"查询表列表失败: {result.get('msg')}")
            for item in result["data"]["items"]:
                tables[item["name"]] = item["table_id"]
            has_more = result["data"].get("has_more", False)
            page_token = result["data"].get("page_token", "")
        return tables

    def create_table(self, name, fields):
        """fields: [{name, type, ...}] 飞书 OpenAPI 字段格式"""
        payload = {
            "table": {
                "name": name,
                "default_view_name": "表格",
                "fields": fields,
            }
        }
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables"
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"创建表 {name} 失败: {result.get('msg')}")
        return result["data"]["table_id"]

    def fetch_existing_order_nos(self, table_id, order_field="订单编号", limit=2000):
        """查询表中已存在的订单编号（用于去重）"""
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records"
        params = {"page_size": 500}
        existing = set()
        has_more, page_token = True, ""
        while has_more and len(existing) < limit:
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"查询记录失败: {result.get('msg')}")
            for item in result["data"]["items"]:
                fv = item.get("fields", {})
                val = fv.get(order_field)
                if val:
                    if isinstance(val, list):
                        for v in val:
                            existing.add(str(v))
                    else:
                        existing.add(str(val))
            has_more = result["data"].get("has_more", False)
            page_token = result["data"].get("page_token", "")
        return existing

    def batch_create_records(self, table_id, records):
        """records: [{fields: {...}}]"""
        total = len(records)
        created = 0
        for i in range(0, total, BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records/batch_create"
            resp = requests.post(
                url, headers=self._headers(),
                json={"records": batch}, timeout=60,
            )
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"批量创建记录失败(第{i // BATCH_SIZE + 1}批): {result.get('msg')} {json.dumps(result)[:300]}")
            created += len(result["data"].get("records", []))
        return created

    def fetch_summary_existing(self, table_id):
        """查询汇总表已有记录，返回 {(日期毫秒, 影院): record_id}"""
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records"
        params = {"page_size": 500}
        existing = {}
        has_more, page_token = True, ""
        while has_more:
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"查询汇总表失败: {result.get('msg')}")
            for item in result["data"].get("items", []):
                fv = item.get("fields", {})
                date_val = fv.get("日期")
                cinema_val = fv.get("所属影院")
                if date_val and cinema_val:
                    if isinstance(cinema_val, list):
                        cinema_val = cinema_val[0].get("text", str(cinema_val[0]))
                    existing[(int(date_val), str(cinema_val))] = item["record_id"]
            has_more = result["data"].get("has_more", False)
            page_token = result["data"].get("page_token", "")
        return existing

    def update_record(self, table_id, record_id, fields):
        """更新单条记录"""
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
        resp = requests.put(url, headers=self._headers(), json={"fields": fields}, timeout=30)
        result = resp.json()
        if result.get("code") != 0:
            raise RuntimeError(f"更新记录失败: {result.get('msg')}")
        return True

    def batch_update_records(self, table_id, records):
        """批量更新 records: [{record_id, fields}]"""
        total = 0
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records/batch_update"
            resp = requests.post(url, headers=self._headers(), json={"records": batch}, timeout=60)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"批量更新失败: {result.get('msg')} {json.dumps(result)[:300]}")
            total += len(result["data"].get("records", []))
        return total

    def search_since(self, table_id, date_field, since_ms):
        """用search接口只查询 date_field >= since_ms 的记录（按日期筛选，避免全表读取）"""
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records/search"
        body = {
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {"field_name": date_field, "operator": "isGreater",
                     "value": ["ExactDate", str(since_ms)]}
                ]
            },
            "page_size": 500
        }
        items, page_token = [], ""
        while True:
            params = {"page_token": page_token} if page_token else {}
            resp = requests.post(url, headers=self._headers(), params=params, json=body, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"按日期查询失败: {result.get('msg')}")
            data = result["data"]
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return items

    def fetch_all_records(self, table_id):
        """分页读取表中所有记录"""
        url = f"{self.base}/bitable/v1/apps/{FEISHU_BASE_TOKEN}/tables/{table_id}/records"
        params = {"page_size": 500}
        all_records = []
        has_more, page_token = True, ""
        while has_more:
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                raise RuntimeError(f"读取记录失败: {result.get('msg')}")
            items = result["data"].get("items", [])
            all_records.extend(items)
            has_more = result["data"].get("has_more", False)
            page_token = result["data"].get("page_token", "")
        return all_records


# 影票表字段定义（飞书 OpenAPI 格式）
TICKET_FIELDS = [
    {"field_name": "放映日期", "type": 5, "ui_type": "DateTime", "field_type": 5},
    {"field_name": "星期", "type": 1},
    {"field_name": "所属影院", "type": 3, "property": {"options": [
        {"name": "欢乐星会影城（原合肥百老汇影城）"}, {"name": "欢乐星会影城（胜利广场CINITY.LED）"}]}},
    {"field_name": "订单编号", "type": 1},
    {"field_name": "商户流水号", "type": 1},
    {"field_name": "订单来源", "type": 1},
    {"field_name": "座位", "type": 1},
    {"field_name": "座位价格(元)", "type": 2, "ui_type": "Number", "property": {"formatter": "0.00"}},
    {"field_name": "实付金额(元)", "type": 2, "ui_type": "Number", "property": {"formatter": "0.00"}},
    {"field_name": "发行价格(元)", "type": 2, "ui_type": "Number", "property": {"formatter": "0.00"}},
    {"field_name": "支付方式", "type": 3, "property": {"options": [
        {"name": "微信支付"}, {"name": "支付宝"}, {"name": "会员卡支付"}, {"name": "现金"}, {"name": "银行卡"}]}},
    {"field_name": "卡号", "type": 1},
    {"field_name": "第三方平台", "type": 1},
    {"field_name": "兑换券价格", "type": 2, "ui_type": "Number", "property": {"formatter": "0.00"}},
    {"field_name": "影片信息", "type": 1},
    {"field_name": "影厅", "type": 1},
    {"field_name": "放映起始时间", "type": 5, "ui_type": "DateTime"},
    {"field_name": "放映结束时间", "type": 5, "ui_type": "DateTime"},
    {"field_name": "用户昵称", "type": 1},
    {"field_name": "会员手机号", "type": 1},
    {"field_name": "后台出票人", "type": 1},
    {"field_name": "购票模式", "type": 1},
    {"field_name": "取票状态", "type": 3, "property": {"options": [{"name": "已取票"}, {"name": "未取票"}]}},
    {"field_name": "取票时间", "type": 5, "ui_type": "DateTime"},
    {"field_name": "取票号", "type": 1},
    {"field_name": "销售时间", "type": 5, "ui_type": "DateTime"},
    {"field_name": "退票信息", "type": 3, "property": {"options": [{"name": "已退票"}, {"name": "未退票"}]}},
    {"field_name": "退票时间", "type": 5, "ui_type": "DateTime"},
    {"field_name": "服务费", "type": 2, "ui_type": "Number", "property": {"formatter": "0.00"}},
]


def main():
    # 计算当日（北京时间）
    now = datetime.datetime.now(CN_TZ)
    today = now.date()
    start_dt = datetime.datetime.combine(today, datetime.time.min, tzinfo=CN_TZ)
    end_dt = datetime.datetime.combine(today, datetime.time.max, tzinfo=CN_TZ)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    month_str = today.strftime("%Y%m")
    print(f"[Main] 目标日期: {today} (北京时间)，月份: {month_str}")

    # 阶段计时
    import time as _time
    _T = {}
    _t0 = _time.time()

    # 1. 抓取欢乐星数据
    hlhx = HLXHClient()
    hlhx.login()
    tickets = hlhx.fetch_tickets(start_ts, end_ts)
    ticket_detail = [t for t in tickets if t.get("orderNo")]
    coupons = hlhx.fetch_coupons(start_ts, end_ts)
    print(f"[Main] 影票: {len(ticket_detail)} 条，兑换券: {len(coupons)} 条")
    _T["1-登录+抓取后台数据"] = _time.time() - _t0; _t0 = _time.time()

    # 2. 飞书初始化
    feishu = FeishuClient()
    feishu.get_tenant_token()
    _T["2-飞书认证"] = _time.time() - _t0; _t0 = _time.time()

    # 3. 定位当月表（list_tables 只调一次，后续复用）
    tables = feishu.list_tables()
    ticket_table_name = f"影票明细_{month_str}"
    if ticket_table_name in tables:
        ticket_table_id = tables[ticket_table_name]
        print(f"[Feishu] 当月表已存在: {ticket_table_name}")
    else:
        ticket_table_id = feishu.create_table(ticket_table_name, TICKET_FIELDS)
        print(f"[Feishu] 已创建当月表: {ticket_table_name}")
    _T["3-定位当月表"] = _time.time() - _t0; _t0 = _time.time()

    # 近三天窗口：去重和汇总共用，只查近三天，不读全表
    recent_dates = set(today - datetime.timedelta(days=i) for i in range(3))
    recent_months = set(d.strftime("%Y%m") for d in recent_dates)
    since_date = today - datetime.timedelta(days=3)
    since_ms = int(datetime.datetime.combine(since_date, datetime.time.min, tzinfo=CN_TZ).timestamp() * 1000)

    def _day_ms(d):
        return int(datetime.datetime.combine(d, datetime.time.min, tzinfo=CN_TZ).timestamp()) * 1000

    def _text(v):
        if isinstance(v, list):
            return v[0].get("text", "") if v else ""
        return v

    def _accum_ticket(fv, summary):
        dv = fv.get("放映日期")
        cinema = _text(fv.get("所属影院"))
        if not dv or not cinema:
            return
        dt = datetime.datetime.fromtimestamp(int(dv) / 1000, tz=CN_TZ)
        if dt.date() not in recent_dates:
            return
        key = (_day_ms(dt.date()), str(cinema))
        s = summary.setdefault(key, {"orders": set(), "people": 0, "boxoffice": 0.0})
        on = _text(fv.get("订单编号"))
        if on:
            s["orders"].add(str(on))
        s["people"] += 1
        pay = fv.get("实付金额(元)")
        if pay is not None:
            s["boxoffice"] += float(pay)

    def _accum_coupon(fv, summary):
        dv = fv.get("兑换时间")
        cinema = _text(fv.get("消费影院"))
        if not dv or not cinema:
            return
        dt = datetime.datetime.fromtimestamp(int(dv) / 1000, tz=CN_TZ)
        if dt.date() not in recent_dates:
            return
        key = (_day_ms(dt.date()), str(cinema))
        s = summary.setdefault(key, {"count": 0, "total": 0.0, "people": 0})
        s["count"] += 1
        fee = fv.get("消费总额")
        if fee is not None:
            s["total"] += float(fee)
        s["people"] += 1

    # 4. 影票：只查近三天记录，去重+汇总共用
    ticket_summary = {}
    existing_ticket_keys = set()
    for tname, tid in tables.items():
        if not tname.startswith("影票明细_"):
            continue
        if tname.replace("影票明细_", "") not in recent_months:
            continue
        recs = feishu.search_since(tid, "放映日期", since_ms)
        print(f"[Feishu] 近三天 {tname}: {len(recs)} 条")
        for item in recs:
            fv = item.get("fields", {})
            existing_ticket_keys.add((str(_text(fv.get("订单编号"))), str(_text(fv.get("座位")))))
            _accum_ticket(fv, ticket_summary)

    new_ticket_records = []
    for t in ticket_detail:
        cell = ticket_to_cell(t)
        if not cell:
            continue
        key = (str(cell.get("订单编号", "")), str(cell.get("座位", "")))
        if key[0] and key in existing_ticket_keys:
            continue
        new_ticket_records.append({"fields": cell})
        existing_ticket_keys.add(key)
        _accum_ticket(cell, ticket_summary)  # 新写入记录同步计入汇总
    print(f"[Feishu] 影票待写入: {len(new_ticket_records)} 条（已按订单+座位去重）")
    if new_ticket_records:
        feishu.batch_create_records(ticket_table_id, new_ticket_records)
    _T["4-影票查询去重写入"] = _time.time() - _t0; _t0 = _time.time()

    # 5. 兑换券：只查近三天记录，去重+汇总共用
    coupon_summary = {}
    recent_coupon = feishu.search_since(FEISHU_COUPON_TABLE_ID, "兑换时间", since_ms)
    print(f"[Feishu] 近三天兑换券: {len(recent_coupon)} 条")
    existing_coupon = set()
    for item in recent_coupon:
        fv = item.get("fields", {})
        on = _text(fv.get("订单编号"))
        if on:
            existing_coupon.add(str(on))
        _accum_coupon(fv, coupon_summary)

    new_coupon_records = []
    for cc in coupons:
        order_no = cc.get("orderNo")
        if order_no and order_no in existing_coupon:
            continue
        cell = coupon_to_cell(cc)
        if cell:
            new_coupon_records.append({"fields": cell})
            if order_no:
                existing_coupon.add(order_no)
            _accum_coupon(cell, coupon_summary)  # 新写入记录同步计入汇总
    print(f"[Feishu] 兑换券待写入: {len(new_coupon_records)} 条（已去重）")
    if new_coupon_records:
        feishu.batch_create_records(FEISHU_COUPON_TABLE_ID, new_coupon_records)
    _T["5-兑换券查询去重写入"] = _time.time() - _t0; _t0 = _time.time()

    # 6. 近三天汇总：批量创建 + 批量更新
    all_keys = set(list(ticket_summary.keys()) + list(coupon_summary.keys()))
    existing_summary = feishu.fetch_summary_existing(FEISHU_SUMMARY_TABLE_ID)
    to_create, to_update = [], []
    for key in sorted(all_keys):
        day_ms, cinema = key
        td = ticket_summary.get(key, {"orders": set(), "people": 0, "boxoffice": 0.0})
        cd = coupon_summary.get(key, {"count": 0, "total": 0.0, "people": 0})
        fields = {
            "日期": day_ms,
            "所属影院": cinema,
            "影票订单数": len(td["orders"]),
            "影票人次": td["people"],
            "影票票房": round(td["boxoffice"], 2),
            "兑换券笔数": cd["count"],
            "兑换券总额": round(cd["total"], 2),
            "兑换券人次": cd["people"],
        }
        if key in existing_summary:
            to_update.append({"record_id": existing_summary[key], "fields": fields})
        else:
            to_create.append({"fields": fields})

    created = feishu.batch_create_records(FEISHU_SUMMARY_TABLE_ID, to_create) if to_create else 0
    updated = feishu.batch_update_records(FEISHU_SUMMARY_TABLE_ID, to_update) if to_update else 0
    print(f"[Feishu] 汇总近三天校准: 共 {len(all_keys)} 条，新增 {created} 条，更新 {updated} 条")
    _T["6-汇总批量写入"] = _time.time() - _t0

    print("[Timing] ===== 脚本内部各阶段耗时 =====")
    _grand = 0
    for _stage, _sec in _T.items():
        print(f"[Timing] {_stage}: {_sec:.2f}s")
        _grand += _sec
    print(f"[Timing] 脚本内部合计: {_grand:.2f}s")
    print(f"[Main] 执行完成：影票写入 {len(new_ticket_records)} 条，兑换券写入 {len(new_coupon_records)} 条，汇总更新 {len(all_keys)} 条")


if __name__ == "__main__":
    main()
