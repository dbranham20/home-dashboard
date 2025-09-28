from datetime import date
import unittest

import dash

class TestCalendar(unittest.TestCase):
  def setUp(self):
    self.app = dash.Dash(__name__)

  def test_first_of_month(self):
    from dashboard.pages.calendar import first_of_month
    assert first_of_month(2024, 1) == date(2024, 1, 1)

  def tearDown(self):
    pass