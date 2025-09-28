import unittest
from unittest.mock import MagicMock, patch
import dash
import pandas as pd
from pandas.testing import assert_frame_equal



class TestCalendar(unittest.TestCase):
  def setUp(self):
    self.app = dash.Dash(__name__)

  def test_fetch_mileage_data_happy_path(self):
    import dashboard.pages.miles_log as miles_log

    # Fake DB rows
    raw = pd.DataFrame(
        {
            "date": ["2024-01-25", "2024-02-15", "2024-03-31"],
            "miles": [10057, 11293, 13397],
        }
    )

    fake_pg = MagicMock()
    fake_pg.connection = object()

    with patch.object(miles_log, "PG", return_value=fake_pg) as mock_pg_ctor, \
         patch.object(miles_log.pd, "read_sql", return_value=raw.copy()) as mock_read_sql:

        df = miles_log.fetch_mileage_data()

        # --- Assert mocks
        mock_pg_ctor.assert_called_once()
        mock_read_sql.assert_called_once()

        # Ensure we used our mocked connection as 2nd positional arg to read_sql
        assert mock_read_sql.call_args[0][1] is fake_pg.connection

        # Current implementation calls close() only after successful read
        fake_pg.close.assert_called_once()

    # --- Build expected frame
    expected = raw.copy()
    expected["Mileage_Diff"] = expected["miles"].diff()
    expected["Date"] = pd.to_datetime(expected["date"])
    expected["Mileage_Increment"] = expected["miles"].diff()
    expected["Days_Diff"] = expected["Date"].diff().dt.days
    expected["Avg_Mileage_Per_Day"] = (
        expected["Mileage_Increment"] / expected["Days_Diff"]
    )

    expected = expected[
        [
            "date",
            "miles",
            "Mileage_Diff",
            "Date",
            "Mileage_Increment",
            "Days_Diff",
            "Avg_Mileage_Per_Day",
        ]
    ]

    assert_frame_equal(df.reset_index(drop=True), expected.reset_index(drop=True))


  def test_fetch_mileage_data_db_error_returns_empty_df(self):
    import dashboard.pages.miles_log as miles_log

    fake_pg = MagicMock()
    fake_pg.connection = object()

    with patch.object(miles_log, "PG", return_value=fake_pg), \
         patch.object(miles_log.pd, "read_sql", side_effect=Exception("boom")):
        result = miles_log.fetch_mileage_data()

    assert isinstance(result, pd.DataFrame)
    assert result.empty
    fake_pg.close.assert_not_called()
