# tests/conftest.py
import pytest
import sys
import os

# Thêm thư mục root vào sys.path để import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Thiết lập môi trường test"""
    original_env = os.environ.copy()

    # Thiết lập biến môi trường test
    os.environ['TESTING'] = '1'

    yield

    # Khôi phục môi trường
    os.environ.clear()
    os.environ.update(original_env)