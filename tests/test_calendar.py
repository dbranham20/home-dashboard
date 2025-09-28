import types
from datetime import date, timedelta
import unittest
from unittest.mock import patch

import dash

class TestCalendar(unittest.TestCase):
  def setUp(self):
    self.app = dash.Dash(__name__)

  def test_first_of_month(self):
    import dashboard.pages.calendar as cal
    assert cal.first_of_month(2025, 9) == date(2025, 9, 1)


  def test_add_month_forward_and_backward(self):
      import dashboard.pages.calendar as cal
      assert cal.add_month(2025, 9, +1) == (2025, 10)
      assert cal.add_month(2025, 12, +1) == (2026, 1)
      assert cal.add_month(2025, 1, -1) == (2024, 12)
      assert cal.add_month(2025, 3, -3) == (2024, 12)


  def test_window_for_month_three_month_span(self):
      import dashboard.pages.calendar as cal
      start, end = cal.window_for_month(2025, 9)
      # Should be first of previous month through first of month after next (exclusive)
      assert start == date(2025, 8, 1)
      assert end == date(2025, 11, 1)


  def test_month_label(self):
      import dashboard.pages.calendar as cal
      assert cal.month_label(2025, 9) == "September 2025"


  def test_shift_month_wraps_years(self):
      import dashboard.pages.calendar as cal
      ctx = cal.shift_month(2025, 11, +2)
      assert (ctx.year, ctx.month) == (2026, 1)
      # backward
      ctx = cal.shift_month(2025, 1, -2)
      assert (ctx.year, ctx.month) == (2024, 11)


  def test_iter_month_days_shape_and_coverage(self):
      import dashboard.pages.calendar as cal

      weeks = cal.iter_month_days(2025, 9)
      # 6 weeks, 7 days each
      assert len(weeks) == 6
      assert all(len(w) == 7 for w in weeks)
      # First cell should be the Sunday (or start-of-grid) before Sep 1, 2025
      # Sep 1, 2025 is Monday; grid should start Sunday Aug 31, 2025
      assert weeks[0][0] == date(2025, 8, 31)
      # Last cell should be 41 days after first
      assert weeks[-1][-1] == weeks[0][0] + timedelta(days=41)


  def test_format_time_12h(self):
      import dashboard.pages.calendar as cal

      assert cal.format_time_12h("17:04") == "5:04 PM"
      assert cal.format_time_12h("00:00") == "12:00 AM"
      assert cal.format_time_12h(None) == ""
      # if parsing fails, returns original
      assert cal.format_time_12h("bad") == "bad"


  def test_label_uses_month_label(self):
      import dashboard.pages.calendar as cal

      out = cal.label({"year": 2025, "month": 9})
      assert out == "September 2025"


  def test_select_day_returns_no_update_if_no_clicks(self):
      import dashboard.pages.calendar as cal

      val = cal.select_day(n_clicks=[0, 0, 0], _1=["2025-09-01", "2025-09-02", "2025-09-03"])
      assert val is dash.no_update


  def test_select_day_picks_triggered_id_date(self):
      import dashboard.pages.calendar as cal

      # Simulate Dash callback_context.triggered_id
      fake_ctx = types.SimpleNamespace(triggered_id={"date": "2025-09-03"})
      with patch.object(cal.dash, "callback_context", fake_ctx):
          out = cal.select_day(n_clicks=[0, 1], _1=["2025-09-02", "2025-09-03"])
      assert out == "2025-09-03"


  def test_show_flash_passthrough(self):
      import dashboard.pages.calendar as cal

      assert cal.show_flash("hello") == "hello"
      assert cal.show_flash("") == ""


  def test_toggle_modal_open_close(self):
      import dashboard.pages.calendar as cal

      # open
      fake_ctx = types.SimpleNamespace(triggered_id="open-add-event")
      with patch.object(cal.dash, "callback_context", fake_ctx):
          opened, title = cal.toggle_modal(1, 0, "2025-09-05", False)
      assert opened is True
      assert "September" in title

      # cancel/close: returns False and keeps title as no_update
      fake_ctx = types.SimpleNamespace(triggered_id="cancel-event")
      with patch.object(cal.dash, "callback_context", fake_ctx):
          opened, title = cal.toggle_modal(0, 1, "2025-09-05", True)
      assert opened is False
      assert title is dash.no_update


  def test_toggle_recur_end_logic(self):
      import dashboard.pages.calendar as cal

      assert cal.toggle_recur_end("daily") is True
      assert cal.toggle_recur_end("weekly") is True
      assert cal.toggle_recur_end("monthly") is True
      assert cal.toggle_recur_end("none") is False
      assert cal.toggle_recur_end(None) is False


  def tearDown(self):
    pass