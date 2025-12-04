# tests/test_reminder_service.py
import pytest
import asyncio
import sqlite3
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime, date, timedelta
import pytz
from bot.services.reminder_service import (
    _deadline_to_midnight_next_day,
    _gather_reminder_payloads,
    _insert_reminder_sent,
    send_daily_reminders,
    send_hourly_reminders,
    TIMEZONE,
    THRESHOLDS
)


class TestReminderServiceHelpers:
    """Test các helper functions"""

    def test_deadline_to_midnight_next_day(self):
        """Test chuyển đổi deadline date thành datetime midnight next day"""
        test_date = date(2024, 1, 15)
        result = _deadline_to_midnight_next_day(test_date)

        assert result.year == 2024
        assert result.month == 1
        assert result.day == 16  # Ngày tiếp theo
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0
        assert result.tzinfo == TIMEZONE

    def test_insert_reminder_sent(self, tmp_path):
        """Test ghi record vào reminders_sent"""
        db_path = tmp_path / "test.db"

        # Tạo database test với schema
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE reminders_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER,
                remind_for_date TEXT,
                mode TEXT,
                sent_at TEXT,
                note TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Test insert
        _insert_reminder_sent(str(db_path), 123, "2024-01-15", "initial", "test note")

        # Verify
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders_sent")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][1] == 123  # requirement_id
        assert rows[0][2] == "2024-01-15"  # remind_for_date
        assert rows[0][3] == "initial"  # mode
        assert rows[0][5] == "test note"  # note


class TestGatherReminderPayloads:
    """Test hàm _gather_reminder_payloads"""

    @pytest.fixture
    def mock_db_schema(self, tmp_path):
        """Tạo database test với schema đầy đủ"""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Tạo tables
        cursor.executescript("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY,
                group_chat_id INTEGER,
                name TEXT
            );

            CREATE TABLE companies (
                company_tax_id TEXT PRIMARY KEY,
                company_name TEXT,
                team_id INTEGER,
                owner_telegram_id INTEGER
            );

            CREATE TABLE requirements (
                id INTEGER PRIMARY KEY,
                company_tax_id TEXT,
                form_code TEXT,
                period TEXT
            );

            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY,
                company_tax_id TEXT,
                form_code TEXT,
                ky_thue TEXT
            );

            CREATE TABLE holidays (
                date TEXT PRIMARY KEY
            );
        """)

        # Thêm dữ liệu test
        cursor.executescript("""
            INSERT INTO teams (id, group_chat_id, name) VALUES
            (1, -100123456, 'Team A'),
            (2, -100789012, 'Team B'),
            (3, NULL, 'Team No Chat');

            INSERT INTO companies (company_tax_id, company_name, team_id, owner_telegram_id) VALUES
            ('C001', 'Company 1', 1, 12345),
            ('C002', 'Company 2', 1, NULL),
            ('C003', 'Company 3', 2, 67890),
            ('C004', 'Company 4', 3, 99999);

            INSERT INTO requirements (id, company_tax_id, form_code, period) VALUES
            (1, 'C001', '01/GTGT', 'monthly'),
            (2, 'C002', '01/GTGT', 'monthly'),
            (3, 'C001', '02/TNDN', 'quarterly'),
            (4, 'C003', '01/GTGT', 'monthly'),
            (5, 'C004', '01/GTGT', 'monthly');

            INSERT INTO submissions (company_tax_id, form_code, ky_thue) VALUES
            ('C001', '01/GTGT', '2024-01');

            INSERT INTO holidays (date) VALUES
            ('2024-01-01'),
            ('2024-01-02');
        """)

        conn.commit()
        conn.close()

        return str(db_path)

    def test_gather_reminder_payloads_basic(self, mock_db_schema, monkeypatch):
        """Test lấy reminder payloads cơ bản"""
        # Mock compute_deadline_for_requirement để trả về deadline cố định
        from bot import utils
        mock_compute = Mock(return_value=(date(2024, 1, 31), "2024-01"))
        monkeypatch.setattr(utils, "compute_deadline_for_requirement", mock_compute)

        # Mock business_days_between để trả về 5 ngày
        monkeypatch.setattr(utils, "business_days_between", Mock(return_value=5))

        # Tham chiếu ngày sao cho days_left <= threshold (monthly: 3)
        # Với mock trả về 5 > 3, nên không có item nào được chọn
        ref_date = date(2024, 1, 20)
        payloads = _gather_reminder_payloads(mock_db_schema, ref_date)

        # Vì days_left = 5 > threshold monthly(3) nên không có item nào
        assert len(payloads) == 0

    def test_gather_reminder_payloads_with_valid_items(self, mock_db_schema, monkeypatch):
        """Test với các item hợp lệ (days_left <= threshold)"""
        from bot import utils

        # Mock để trả về days_left = 2 (<= threshold monthly: 3)
        def mock_business_days_between(start, end, holidays):
            return 2

        monkeypatch.setattr(utils, "business_days_between", mock_business_days_between)

        # Mock compute_deadline
        monkeypatch.setattr(utils, "compute_deadline_for_requirement",
                            Mock(return_value=(date(2024, 1, 31), "2024-01")))

        ref_date = date(2024, 1, 20)
        payloads = _gather_reminder_payloads(mock_db_schema, ref_date)

        # Chỉ có 2 requirements chưa nộp:
        # - requirement 2 (C002, monthly) - không có submission
        # - requirement 3 (C001, quarterly) - không có submission cho form 02/TNDN
        # - requirement 4 (C003, monthly) - không có submission
        # Requirement 1 đã có submission nên bị bỏ qua
        # Requirement 5 thuộc team không có chat_id nên không được thêm vào payloads

        assert len(payloads) == 2  # Team A và Team B

        # Kiểm tra Team A
        team_a = next(p for p in payloads if p["team_id"] == 1)
        assert team_a["chat_id"] == -100123456
        assert team_a["team_name"] == "Team A"
        assert len(team_a["items"]) == 2  # requirement 2 và 3

        # Kiểm tra Team B
        team_b = next(p for p in payloads if p["team_id"] == 2)
        assert team_b["chat_id"] == -100789012
        assert len(team_b["items"]) == 1  # requirement 4

    def test_gather_reminder_payloads_no_holidays_table(self, tmp_path, monkeypatch):
        """Test khi không có bảng holidays"""
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Chỉ tạo tables cơ bản, không có holidays
        cursor.executescript("""
            CREATE TABLE teams (id INTEGER PRIMARY KEY, group_chat_id INTEGER, name TEXT);
            CREATE TABLE companies (company_tax_id TEXT PRIMARY KEY, company_name TEXT, team_id INTEGER);
            CREATE TABLE requirements (id INTEGER PRIMARY KEY, company_tax_id TEXT, form_code TEXT, period TEXT);
        """)

        cursor.executescript("""
            INSERT INTO teams (id, group_chat_id, name) VALUES (1, -100123456, 'Team A');
            INSERT INTO companies (company_tax_id, company_name, team_id) VALUES ('C001', 'Company 1', 1);
            INSERT INTO requirements (id, company_tax_id, form_code, period) VALUES (1, 'C001', '01/GTGT', 'monthly');
        """)

        conn.commit()
        conn.close()

        # Mock các hàm utils
        from bot import utils
        monkeypatch.setattr(utils, "compute_deadline_for_requirement",
                            Mock(return_value=(date(2024, 1, 31), "2024-01")))
        monkeypatch.setattr(utils, "business_days_between", Mock(return_value=2))

        payloads = _gather_reminder_payloads(str(db_path), date(2024, 1, 20))

        # Không có lỗi, hàm vẫn chạy được
        assert len(payloads) == 1


class TestSendDailyReminders:
    """Test hàm send_daily_reminders"""

    @pytest.fixture
    def mock_app(self):
        """Tạo mock application"""
        app = Mock()
        app.bot = AsyncMock()
        return app

    @pytest.mark.asyncio
    async def test_send_daily_reminders_empty(self, mock_app):
        """Test khi không có reminder nào"""
        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = []

            await send_daily_reminders(mock_app, "/fake/db/path")

            # Không gửi tin nhắn nào
            mock_app.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_daily_reminders_with_owner(self, mock_app, monkeypatch):
        """Test gửi reminder có owner"""
        # Mock payload với owner
        payloads = [{
            "team_id": 1,
            "chat_id": -100123456,
            "team_name": "Team A",
            "items": [{
                "requirement_id": 1,
                "company_tax": "C001",
                "company_name": "Company 1",
                "form_code": "01/GTGT",
                "period_str": "2024-01",
                "deadline": date(2024, 1, 31),
                "days_left": 2,
                "owner_id": 12345
            }]
        }]

        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = payloads

            # Mock _insert_reminder_sent
            mock_insert = Mock()
            monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

            await send_daily_reminders(mock_app, "/fake/db/path")

            # Kiểm tra đã gửi tin nhắn
            mock_app.bot.send_message.assert_called_once()

            # Kiểm tra nội dung tin nhắn có tag owner
            call_args = mock_app.bot.send_message.call_args
            assert call_args.kwargs['chat_id'] == -100123456
            assert "tg://user?id=12345" in call_args.kwargs['text']

            # Kiểm tra đã insert reminder sent
            mock_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_daily_reminders_chunking(self, mock_app, monkeypatch):
        """Test chunking khi có nhiều items"""
        # Tạo nhiều items (hơn CHUNK_SIZE)
        items = []
        for i in range(20):  # CHUNK_SIZE = 15, nên chia thành 2 chunks
            items.append({
                "requirement_id": i,
                "company_tax": f"C{i:03d}",
                "company_name": f"Company {i}",
                "form_code": "01/GTGT",
                "period_str": "2024-01",
                "deadline": date(2024, 1, 31),
                "days_left": 2,
                "owner_id": None
            })

        payloads = [{
            "team_id": 1,
            "chat_id": -100123456,
            "team_name": "Team A",
            "items": items
        }]

        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = payloads

            # Mock _insert_reminder_sent
            mock_insert = Mock()
            monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

            await send_daily_reminders(mock_app, "/fake/db/path")

            # Kiểm tra đã gửi 2 tin nhắn (1 header + 20 items = 21 dòng, chunk size 15)
            assert mock_app.bot.send_message.call_count == 2

            # Kiểm tra số lần insert
            assert mock_insert.call_count == 20

    @pytest.mark.asyncio
    async def test_send_daily_reminders_exception_handling(self, mock_app, monkeypatch):
        """Test xử lý exception khi gửi tin nhắn"""
        payloads = [{
            "team_id": 1,
            "chat_id": -100123456,
            "team_name": "Team A",
            "items": [{
                "requirement_id": 1,
                "company_tax": "C001",
                "company_name": "Company 1",
                "form_code": "01/GTGT",
                "period_str": "2024-01",
                "deadline": date(2024, 1, 31),
                "days_left": 2,
                "owner_id": 12345
            }]
        }]

        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = payloads

            # Mock send_message để raise exception
            mock_app.bot.send_message.side_effect = Exception("API Error")

            # Mock _insert_reminder_sent
            mock_insert = Mock()
            monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

            # Không nên raise exception
            await send_daily_reminders(mock_app, "/fake/db/path")

            # Insert không được gọi vì gửi thất bại
            mock_insert.assert_not_called()


class TestSendHourlyReminders:
    """Test hàm send_hourly_reminders"""

    @pytest.fixture
    def mock_app(self):
        app = Mock()
        app.bot = AsyncMock()
        return app

    @pytest.mark.asyncio
    async def test_send_hourly_reminders_within_24h(self, mock_app, monkeypatch):
        """Test gửi reminder trong vòng 24h"""
        # Mock datetime.now để kiểm soát thời gian
        mock_now = datetime(2024, 1, 31, 10, 0, 0, tzinfo=TIMEZONE)  # 10AM ngày deadline
        with patch('bot.services.reminder_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            # Mock _deadline_to_midnight_next_day
            deadline_date = date(2024, 1, 31)
            midnight_next = datetime(2024, 2, 1, 0, 0, 0, tzinfo=TIMEZONE)
            monkeypatch.setattr('bot.services.reminder_service._deadline_to_midnight_next_day',
                                Mock(return_value=midnight_next))

            # Mock payload
            payloads = [{
                "team_id": 1,
                "chat_id": -100123456,
                "team_name": "Team A",
                "items": [{
                    "requirement_id": 1,
                    "company_tax": "C001",
                    "company_name": "Company 1",
                    "form_code": "01/GTGT",
                    "period_str": "2024-01",
                    "deadline": deadline_date,
                    "days_left": 0,
                    "owner_id": 12345
                }]
            }]

            with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
                mock_gather.return_value = payloads

                # Mock _last_hourly_sent để trả về None (chưa gửi lần nào)
                def mock_last_sent(db_path, req_id, remind_date):
                    return None

                monkeypatch.setattr('bot.services.reminder_service._last_hourly_sent', mock_last_sent)

                # Mock _insert_reminder_sent
                mock_insert = Mock()
                monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

                await send_hourly_reminders(mock_app, "/fake/db/path")

                # Kiểm tra đã gửi tin nhắn
                mock_app.bot.send_message.assert_called_once()
                mock_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_hourly_reminders_rate_limit(self, mock_app, monkeypatch):
        """Test rate limiting - không gửi nếu đã gửi trong vòng 1 giờ"""
        mock_now = datetime(2024, 1, 31, 10, 0, 0, tzinfo=TIMEZONE)

        with patch('bot.services.reminder_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            deadline_date = date(2024, 1, 31)
            midnight_next = datetime(2024, 2, 1, 0, 0, 0, tzinfo=TIMEZONE)
            monkeypatch.setattr('bot.services.reminder_service._deadline_to_midnight_next_day',
                                Mock(return_value=midnight_next))

            payloads = [{
                "team_id": 1,
                "chat_id": -100123456,
                "team_name": "Team A",
                "items": [{
                    "requirement_id": 1,
                    "company_tax": "C001",
                    "company_name": "Company 1",
                    "form_code": "01/GTGT",
                    "period_str": "2024-01",
                    "deadline": deadline_date,
                    "days_left": 0,
                    "owner_id": 12345
                }]
            }]

            with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
                mock_gather.return_value = payloads

                # Mock _last_hourly_sent để trả về thời gian 30 phút trước
                def mock_last_sent(db_path, req_id, remind_date):
                    # Trả về thời gian UTC, 30 phút trước
                    return "2024-01-31 01:30:00"  # 1:30AM UTC = 8:30AM Bangkok time

                monkeypatch.setattr('bot.services.reminder_service._last_hourly_sent', mock_last_sent)

                # Mock _insert_reminder_sent
                mock_insert = Mock()
                monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

                await send_hourly_reminders(mock_app, "/fake/db/path")

                # Không gửi vì chưa đủ 1 giờ
                mock_app.bot.send_message.assert_not_called()
                mock_insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_hourly_reminders_outside_window(self, mock_app, monkeypatch):
        """Test không gửi khi ngoài cửa sổ 24h"""
        mock_now = datetime(2024, 1, 30, 0, 0, 0, tzinfo=TIMEZONE)  # 2 ngày trước deadline

        with patch('bot.services.reminder_service.datetime') as mock_datetime:
            mock_datetime.now.return_value = mock_now

            deadline_date = date(2024, 2, 1)  # Deadline trong 2 ngày nữa
            midnight_next = datetime(2024, 2, 2, 0, 0, 0, tzinfo=TIMEZONE)
            monkeypatch.setattr('bot.services.reminder_service._deadline_to_midnight_next_day',
                                Mock(return_value=midnight_next))

            payloads = [{
                "team_id": 1,
                "chat_id": -100123456,
                "team_name": "Team A",
                "items": [{
                    "requirement_id": 1,
                    "company_tax": "C001",
                    "company_name": "Company 1",
                    "form_code": "01/GTGT",
                    "period_str": "2024-01",
                    "deadline": deadline_date,
                    "days_left": 2,
                    "owner_id": 12345
                }]
            }]

            with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
                mock_gather.return_value = payloads

                # Mock _insert_reminder_sent
                mock_insert = Mock()
                monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

                await send_hourly_reminders(mock_app, "/fake/db/path")

                # Không gửi vì còn hơn 24h
                mock_app.bot.send_message.assert_not_called()
                mock_insert.assert_not_called()


# Test integration với database thật
class TestReminderServiceIntegration:
    """Test integration với SQLite database"""

    @pytest.fixture
    def test_database(self, tmp_path):
        """Tạo database test hoàn chỉnh"""
        db_path = tmp_path / "integration.db"

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Schema đầy đủ
        cursor.executescript("""
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY,
                group_chat_id INTEGER,
                name TEXT
            );

            CREATE TABLE companies (
                company_tax_id TEXT PRIMARY KEY,
                company_name TEXT,
                team_id INTEGER,
                owner_telegram_id INTEGER
            );

            CREATE TABLE requirements (
                id INTEGER PRIMARY KEY,
                company_tax_id TEXT,
                form_code TEXT,
                period TEXT
            );

            CREATE TABLE submissions (
                id INTEGER PRIMARY KEY,
                company_tax_id TEXT,
                form_code TEXT,
                ky_thue TEXT
            );

            CREATE TABLE holidays (
                date TEXT PRIMARY KEY
            );

            CREATE TABLE reminders_sent (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id INTEGER,
                remind_for_date TEXT,
                mode TEXT,
                sent_at TEXT DEFAULT (datetime('now')),
                note TEXT
            );
        """)

        # Thêm dữ liệu test phức tạp hơn
        cursor.executescript("""
            -- Teams
            INSERT INTO teams (id, group_chat_id, name) VALUES
            (1, -100111111, 'Sales Team'),
            (2, -100222222, 'Support Team');

            -- Companies với owners
            INSERT INTO companies (company_tax_id, company_name, team_id, owner_telegram_id) VALUES
            ('TAX001', 'ABC Corp', 1, 11111),
            ('TAX002', 'XYZ Ltd', 1, NULL),
            ('TAX003', 'DEF Inc', 2, 22222),
            ('TAX004', 'GHI LLC', 2, 22222);

            -- Requirements với các tần suất khác nhau
            INSERT INTO requirements (id, company_tax_id, form_code, period) VALUES
            (1, 'TAX001', '01/GTGT', 'monthly'),
            (2, 'TAX001', '02/TNDN', 'quarterly'),
            (3, 'TAX002', '01/GTGT', 'monthly'),
            (4, 'TAX003', '01/GTGT', 'monthly'),
            (5, 'TAX004', '03/TNCN', 'monthly');

            -- Một submission đã nộp
            INSERT INTO submissions (company_tax_id, form_code, ky_thue) VALUES
            ('TAX001', '01/GTGT', '2024-01');

            -- Holidays
            INSERT INTO holidays (date) VALUES
            ('2024-01-01'),
            ('2024-02-10'),
            ('2024-02-11'),
            ('2024-02-12');
        """)

        conn.commit()
        conn.close()

        return str(db_path)

    def test_full_reminder_flow(self, test_database, monkeypatch):
        """Test toàn bộ flow reminder với database thật"""
        from bot import utils

        # Mock compute_deadline_for_requirement
        def mock_compute(freq, ref_date):
            if freq == 'monthly':
                return date(2024, 1, 20), "2024-01"  # Deadline gần
            elif freq == 'quarterly':
                return date(2024, 3, 31), "2024-Q1"
            return None, None

        monkeypatch.setattr(utils, "compute_deadline_for_requirement", mock_compute)

        # Mock business_days_between để trả về 1 ngày (<= threshold)
        monkeypatch.setattr(utils, "business_days_between", Mock(return_value=1))

        ref_date = date(2024, 1, 18)  # 2 ngày trước deadline monthly
        payloads = _gather_reminder_payloads(test_database, ref_date)

        # Kiểm tra kết quả:
        # - TAX001/01/GTGT đã có submission nên bị bỏ qua
        # - TAX001/02/TNDN (quarterly) có deadline xa hơn
        # - TAX002/01/GTGT (monthly) chưa nộp
        # - TAX003/01/GTGT (monthly) chưa nộp
        # - TAX004/03/TNCN (monthly) chưa nộp

        assert len(payloads) == 2  # 2 teams

        # Team 1 (Sales Team)
        team1 = next(p for p in payloads if p["team_id"] == 1)
        assert len(team1["items"]) == 1  # Chỉ TAX002

        # Team 2 (Support Team)
        team2 = next(p for p in payloads if p["team_id"] == 2)
        assert len(team2["items"]) == 2  # TAX003 và TAX004


# Test edge cases
class TestReminderServiceEdgeCases:
    """Test các edge cases"""

    @pytest.mark.asyncio
    async def test_send_to_chat_without_owner_tag(self, mock_app, monkeypatch):
        """Test gửi tin nhắn không có owner tag khi owner_id không có"""
        payloads = [{
            "team_id": 1,
            "chat_id": -100123456,
            "team_name": "Team A",
            "items": [{
                "requirement_id": 1,
                "company_tax": "C001",
                "company_name": "Company 1",
                "form_code": "01/GTGT",
                "period_str": "2024-01",
                "deadline": date(2024, 1, 31),
                "days_left": 2,
                "owner_id": None  # Không có owner
            }]
        }]

        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = payloads

            # Mock _insert_reminder_sent
            mock_insert = Mock()
            monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

            await send_daily_reminders(mock_app, "/fake/db/path")

            # Kiểm tra đã gửi tin nhắn không có tag
            mock_app.bot.send_message.assert_called_once()
            call_args = mock_app.bot.send_message.call_args
            assert "tg://user" not in call_args.kwargs['text']

    def test_threshold_config(self):
        """Test cấu hình thresholds"""
        assert THRESHOLDS["monthly"] == 3
        assert THRESHOLDS["quarterly"] == 3
        assert THRESHOLDS["default"] == 10

        # Test với tần suất không có trong config
        assert THRESHOLDS.get("yearly", THRESHOLDS["default"]) == 10

    @pytest.mark.asyncio
    async def test_reminder_with_invalid_chat_id(self, mock_app, monkeypatch):
        """Test với chat_id không hợp lệ"""
        payloads = [{
            "team_id": 1,
            "chat_id": 0,  # Chat ID không hợp lệ
            "team_name": "Team A",
            "items": [{
                "requirement_id": 1,
                "company_tax": "C001",
                "company_name": "Company 1",
                "form_code": "01/GTGT",
                "period_str": "2024-01",
                "deadline": date(2024, 1, 31),
                "days_left": 2,
                "owner_id": 12345
            }]
        }]

        with patch('bot.services.reminder_service._gather_reminder_payloads') as mock_gather:
            mock_gather.return_value = payloads

            # Mock _insert_reminder_sent
            mock_insert = Mock()
            monkeypatch.setattr('bot.services.reminder_service._insert_reminder_sent', mock_insert)

            # Nên raise exception khi gửi với chat_id không hợp lệ
            mock_app.bot.send_message.side_effect = Exception("Invalid chat_id")

            # Không nên raise exception từ hàm chính
            await send_daily_reminders(mock_app, "/fake/db/path")

            # Insert không được gọi
            mock_insert.assert_not_called()


if __name__ == "__main__":
    # Import ở đây để tránh circular imports
    import sqlite3

    pytest.main([__file__, "-v"])