
import asyncio
import concurrent

from microurl import bitlyapi

ACCESS_TOKEN = 'PUT AN ACCESS TOKEN HERE IDK WHERE I GOT IT FROM ITS FOR BIT.LY BUT THIS FILE IS BADLY NAMED'

async def shorten_url(url):

    bitly=bitlyapi(ACCESS_TOKEN)
    
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
    loop = asyncio.get_event_loop()
    
    def get_minified_url(longurl):
        return bitly.shorturl(longurl)['url']
        
    future = loop.run_in_executor(executor, get_minified_url, url)
                
    r = await future
    return r