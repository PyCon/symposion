import re


class ProposalProxy(object):
    ''' Proxy object that allows for proposals to have their speaker
    redacted. '''

    def __init__(self, proposal):
        self.__proposal__ = proposal

    def __getattr__(self, attr):
        ''' Overridden __getattr__ that hides the available speakers. '''

        if attr == "speaker":
            return Parrot("Primary Speaker")
        elif attr == "additional_speakers":
            return None
        elif attr == "speakers":
            return self._speakers
#        elif attr in ("description", "description_html", "abstract", "abstract_html"):
#            return Parrot(self._redact(getattr(self.__proposal__, attr)))
        else:
            return getattr(self.__proposal__, attr)

    def _speakers(self):
        for i, j in enumerate(self.__proposal__.speakers()):
            if i == 0:
                yield self.speaker
            else:
                yield Parrot("Additional speaker " + str(i))

    def _redact(self, val, replacement="REDACTED"):
        full_names = [str(i) for i in self.__proposal__.speakers()]
        individual_names = [j for i in full_names for j in i.split()]
        val = self._replaceany(val, full_names, replacement)
        return self._replaceany(val, individual_names, replacement)

    def _replaceany(self, source, items, destination):
        rx = re.compile(
            r"\b(" + "|".join(re.escape(i) for i in items) + r")\b", re.IGNORECASE
        )
        return rx.sub(destination, source)


class MessageProxy(object):
    ''' Proxy object that allows messages to redact the speaker name. '''

    def __init__(self, message):
        self.__message__ = message

    def __getattr__(self, attr):
        message = self.__message__

        if attr == "user":
            if hasattr(message.user, "speaker_profile"):
                if message.user.speaker_profile in message.proposal.speakers():
                  user = Parrot("A Speaker")
            else:
                user = message.user
            return user

        return getattr(message, attr)


class Parrot(object):
    ''' Placeholder object for speakers. For *any* __getattr__ call, it will
    repeat back the name it was given. '''

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    def __getattr__(self, attr):
        return self.name
