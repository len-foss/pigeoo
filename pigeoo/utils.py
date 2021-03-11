import logging

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger("pigeoo")

Path = str


def file_write(content, output_name):
    with open(output_name, 'w') as output:
        output.write(content)
    return output_name
