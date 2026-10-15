"""Periodic allocator maintenance for the gateway's existing housekeeper."""


def housekeeping_memory_trim():
    from hermes_cli.mem_trim import trim_memory
    trim_memory(reason='messaging gateway housekeeping')
