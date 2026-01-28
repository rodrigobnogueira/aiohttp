import asyncio
import gc
import warnings
from unittest import mock
from aiohttp.connector import Connection

def test_leak_closed_loop():
    loop = asyncio.new_event_loop()
    connector = mock.Mock()
    key = mock.Mock()
    protocol = mock.Mock()
    
    conn = Connection(connector, key, protocol, loop=loop)
    
    print("Closing loop")
    loop.close()
    
    print("Deleting conn")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        del conn
        gc.collect()
        print(f"Warnings caught: {len(w)}")
        for warning in w:
            print(f"Warning: {warning.message}")
            if issubclass(warning.category, ResourceWarning) and "Unclosed connection" in str(warning.message):
                print("Reproduced: Unclosed connection warning after loop close")

if __name__ == "__main__":
    test_leak_closed_loop()
