from configparser import ConfigParser
import logging
from contextlib import suppress

logger = logging.getLogger(__name__)

'''
# format
[user]
marketplace = au

[ignore_series]
1 = series title
2 = series2 title
...
'''

def load_config(filename: str='config.ini') -> ConfigParser:
    '''Loads config file'''
    config = ConfigParser()
    with suppress():
        config.read(filename)
        logger.info(f'Successfully loaded {filename}')
    return config

def save_config(config: ConfigParser, filename: str='config.ini'):
    '''Save config file'''
    with open(filename, 'w') as f:
        config.write(f)
        logger.info(f'Successfully saved {filename}')
