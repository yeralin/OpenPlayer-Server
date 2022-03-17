
class Version(dict):
    
    def __init__(self, version: str):
        self.version = version
        dict.__init__(self, self.__dict__)

class Entry(dict):

    def __init__(self, title: str, url: str, source: str) -> None:
        self.title = title
        self.url = url
        self.source = source
        dict.__init__(self, self.__dict__)
