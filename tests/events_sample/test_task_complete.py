from openhands.events.event_store import EventStore
from openhands.memory.condenser.impl.composite_condenser import (
    TaskCompletionBrowserCondenser,
)
from openhands.memory.view import View
from openhands.storage import get_file_store

file_store = get_file_store('local', '/tmp/openhands_file_store/')

events = EventStore(
    # "699ce247862548a5803a95e5fd3a0bcf",
    'b9ec6682e66f4ad78966935e7571faa4',
    file_store,
    '0xa294d8218e3a35cf5135d200e685592ed01079b1',
)

view = View.from_events(list(events.get_events()))

condenser = TaskCompletionBrowserCondenser(keep_first=1, browser_attention_window=1)

# condenser = TaskCompletionCondenser(keep_first=1)

res = condenser.condense(view)

print(res)
