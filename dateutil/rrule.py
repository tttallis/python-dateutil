"""
Copyright (c) 2003-2010  Gustavo Niemeyer <gustavo@niemeyer.net>

This module offers extensions to the standard python 2.3+
datetime module.
"""
__author__ = "Gustavo Niemeyer <gustavo@niemeyer.net>"
__license__ = "PSF License"

import itertools
import datetime
import calendar
import thread
import heapq
import sys
import re
from utils import ordinal

__all__ = ["rrule", "rruleset", "rrulestr",
           "YEARLY", "MONTHLY", "WEEKLY", "DAILY",
           "HOURLY", "MINUTELY", "SECONDLY",
           "MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# Every mask is 7 days longer to handle cross-year weekly periods.
M366MASK = tuple([1]*31+[2]*29+[3]*31+[4]*30+[5]*31+[6]*30+
                 [7]*31+[8]*31+[9]*30+[10]*31+[11]*30+[12]*31+[1]*7)
M365MASK = list(M366MASK)
M29, M30, M31 = range(1,30), range(1,31), range(1,32)
MDAY366MASK = tuple(M31+M29+M31+M30+M31+M30+M31+M31+M30+M31+M30+M31+M31[:7])
MDAY365MASK = list(MDAY366MASK)
M29, M30, M31 = range(-29,0), range(-30,0), range(-31,0)
NMDAY366MASK = tuple(M31+M29+M31+M30+M31+M30+M31+M31+M30+M31+M30+M31+M31[:7])
NMDAY365MASK = list(NMDAY366MASK)
M366RANGE = (0,31,60,91,121,152,182,213,244,274,305,335,366)
M365RANGE = (0,31,59,90,120,151,181,212,243,273,304,334,365)
WDAYMASK = [0,1,2,3,4,5,6]*55
del M29, M30, M31, M365MASK[59], MDAY365MASK[59], NMDAY365MASK[31]
MDAY365MASK = tuple(MDAY365MASK)
M365MASK = tuple(M365MASK)

(YEARLY,
 MONTHLY,
 WEEKLY,
 DAILY,
 HOURLY,
 MINUTELY,
 SECONDLY) = range(7)
FREQNAMES = ['YEARLY','MONTHLY','WEEKLY','DAILY','HOURLY','MINUTELY','SECONDLY']
(REPETITION_ONLY, NORMAL, FULLY_RESOLVED) = range(3)

DATETIME_FORMAT = '%Y%m%dT%H%M%S' # won't cope with aware datetimes
HUMAN_WEEKDAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']

# Imported on demand.
easter = None
parser = None

class weekday(object):
    __slots__ = ["weekday", "n"]

    def __init__(self, weekday, n=None):
        if n == 0:
            raise ValueError, "Can't create weekday with n == 0"
        self.weekday = weekday
        self.n = n

    def __call__(self, n):
        if n == self.n:
            return self
        else:
            return self.__class__(self.weekday, n)

    def __eq__(self, other):
        try:
            if self.weekday != other.weekday or self.n != other.n:
                return False
        except AttributeError:
            return False
        return True

    def __repr__(self):
        s = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[self.weekday]
        if not self.n:
            return s
        else:
            return "%s(%+d)" % (s, self.n)

MO, TU, WE, TH, FR, SA, SU = weekdays = tuple([weekday(x) for x in range(7)])

class rrulebase:
    def __init__(self, cache=False):
        if cache:
            self._cache = []
            self._cache_lock = thread.allocate_lock()
            self._cache_gen  = self._iter()
            self._cache_complete = False
        else:
            self._cache = None
            self._cache_complete = False
        self._len = None

    def __iter__(self):
        if self._cache_complete:
            return iter(self._cache)
        elif self._cache is None:
            return self._iter()
        else:
            return self._iter_cached()

    def _iter_cached(self):
        i = 0
        gen = self._cache_gen
        cache = self._cache
        acquire = self._cache_lock.acquire
        release = self._cache_lock.release
        while gen:
            if i == len(cache):
                acquire()
                if self._cache_complete:
                    break
                try:
                    for j in range(10):
                        cache.append(gen.next())
                except StopIteration:
                    self._cache_gen = gen = None
                    self._cache_complete = True
                    break
                release()
            yield cache[i]
            i += 1
        while i < self._len:
            yield cache[i]
            i += 1

    def __getitem__(self, item):
        if self._cache_complete:
            return self._cache[item]
        elif isinstance(item, slice):
            if item.step and item.step < 0:
                return list(iter(self))[item]
            else:
                return list(itertools.islice(self,
                                             item.start or 0,
                                             item.stop or sys.maxint,
                                             item.step or 1))
        elif item >= 0:
            gen = iter(self)
            try:
                for i in range(item+1):
                    res = gen.next()
            except StopIteration:
                raise IndexError
            return res
        else:
            return list(iter(self))[item]

    def __contains__(self, item):
        if self._cache_complete:
            return item in self._cache
        else:
            for i in self:
                if i == item:
                    return True
                elif i > item:
                    return False
        return False

    # __len__() introduces a large performance penality.
    def count(self):
        if not self._until:
            return -1
        if self._len is None:
            for x in self: pass
        return self._len

    def before(self, dt, inc=False):
        if self._cache_complete:
            gen = self._cache
        else:
            gen = self
        last = None
        if inc:
            for i in gen:
                if i > dt:
                    break
                last = i
        else:
            for i in gen:
                if i >= dt:
                    break
                last = i
        return last

    def after(self, dt, inc=False):
        if self._cache_complete:
            gen = self._cache
        else:
            gen = self
        if inc:
            for i in gen:
                if i >= dt:
                    return i
        else:
            for i in gen:
                if i > dt:
                    return i
        return None

    def between(self, after, before, inc=False):
        if self._cache_complete:
            gen = self._cache
        else:
            gen = self
        started = False
        l = []
        if inc:
            for i in gen:
                if i > before:
                    break
                elif not started:
                    if i >= after:
                        started = True
                        l.append(i)
                else:
                    l.append(i)
        else:
            for i in gen:
                if i >= before:
                    break
                elif not started:
                    if i > after:
                        started = True
                        l.append(i)
                else:
                    l.append(i)
        return l
        
(TERSE, NORMAL, VERBOSE, DEBUG)=range(4)

class HumanizerBase(object):
    def render_time(self, dt):
        if self.verbosity < VERBOSE:  
            if dt.minute:
                return datetime.datetime.strftime(dt, '%I:%M%p').lstrip('0').lower()
            else:
                return datetime.datetime.strftime(dt, '%I%p').lstrip('0').lower()
        else:
            return datetime.datetime.strftime(dt, '%I:%M%p').lstrip('0').lower()
    
    def render_day(self, dt):
        def terse():
            return datetime.datetime.strftime(dt, '%d %b')
            
        def normal():
            return datetime.datetime.strftime(dt, '%a %d %b')
        
        def verbose():
            return datetime.datetime.strftime(dt, '%A %d %B')

        return {
            TERSE:terse(),
            NORMAL:normal(),
            VERBOSE:verbose(),
            DEBUG:verbose(),  # nota bene!
        }[self.verbosity]
        
class RRuleHumanizer(HumanizerBase): # add a convenient hook so this can be overridden
    def __init__(self, rrule, verbosity=NORMAL):
        self.dt = rrule._dtstart
        self.freq = rrule._freq
        self.interval = rrule._interval
        self.wkst = rrule._wkst
        self.until = rrule._until
        self.bymonth = rrule._bymonth
        self.byweekno = rrule._byweekno
        self.byyearday = rrule._byyearday
        self.byweekday = rrule._byweekday
        self.byeaster = rrule._byeaster
        self.bymonthday = rrule._bymonthday
        self.bynmonthday = rrule._bynmonthday
        self.bysetpos = rrule._bysetpos
        self.byhour = rrule._byhour
        self.byminute = rrule._byminute
        self.bysecond = rrule._bysecond
        self.verbosity = verbosity
        
    def render(self):
        if self.until:
            return "%(start)s - %(until)s, %(time)s %(repeat)s" % {
                'start':self.render_start(),
                'until':self.render_until(),
                'time':self.render_time(self.dt),
                'repeat':self.render_repeat(),
            }
        else:
            return "from %(start)s, %(time)s %(repeat)s" % {
                'start':self.render_start(),
                'time':self.render_time(self.dt),
                'repeat':self.render_repeat(),
            }
#             return "%(datetime)s%(repeat)s" % {'datetime':self.render_start(), 'repeat':self.render_repeat()}
                
    def render_start(self):
        if self.until and self.dt.year == self.until.year:
            return self.render_day(self.dt)
        else:
            return "%s %d" % (self.render_day(self.dt), self.dt.year)
                
    def render_until(self):
        return "%s %d" % (self.render_day(self.until), self.until.year)
            
    def render_interval(self):
        if self.interval != 1:
            return ' %s' % ordinal(self.interval)
        else:
            return ''
    
    def render_repeat(self):
        if self.verbosity > 1:
            verbiage = "repeating "
        else:
            verbiage = "- "
        if self.freq == YEARLY:
            monthstr = datetime.datetime.strftime(self.dt, "%B")
            return "%s%s %s, every%s year from %s" % (
                verbiage,
                monthstr, 
                ordinal(self.dt.day), 
                self.interval, 
                self.dt.year,
            )
        elif self.freq == MONTHLY:
            return "Monthly repetitions not humanized yet"
        elif self.freq == WEEKLY:
            weekdaystr = ', '.join([HUMAN_WEEKDAYS[day] for day in self.byweekday])
            return "%severy %s" % (verbiage, weekdaystr)
        elif self.freq == DAILY:
            return "%sdaily" % verbiage
            

class rrule(rrulebase):
    def humanize(self, verbosity=NORMAL):
        humanizer = RRuleHumanizer(self, verbosity=verbosity)
        return humanizer.render()
    
    def __init__(self, freq, dtstart=None,
                 interval=None, wkst=None, count=None, until=None, bysetpos=None,
                 bymonth=None, bymonthday=None, byyearday=None, byeaster=None,
                 byweekno=None, byweekday=None,
                 byhour=None, byminute=None, bysecond=None,
                 cache=False, normalized_start=False,
                 original_str='',):
                 
        kwargs = locals().copy()
        del kwargs['self']
        if 'original_str' in kwargs:
            del kwargs['original_str']
        
        original_kwargs = dict((k,v) for k,v in kwargs.iteritems() if v is not None and v is not False and not isinstance(v, datetime.datetime))
        self.original_params = {name.upper().replace('BYWEEKDAY', 'BYDAY'): val for name,val in original_kwargs.items()}

        if not interval: # needed to work around checking the kwargs
            interval = 1
        rrulebase.__init__(self, cache)
        global easter
        self._original_str = original_str
        if not dtstart:
            dtstart = datetime.datetime.now().replace(microsecond=0)
        elif not isinstance(dtstart, datetime.datetime):
            dtstart = datetime.datetime.fromordinal(dtstart.toordinal())
        else:
            dtstart = dtstart.replace(microsecond=0)
        self._dtstart = dtstart
        self._tzinfo = dtstart.tzinfo
        self._freq = freq
        self._interval = interval
        self._count = count
        if until and not isinstance(until, datetime.datetime):
            until = datetime.datetime.fromordinal(until.toordinal())
        self._until = until
        if wkst is None:
            self._wkst = calendar.firstweekday()
        elif type(wkst) is int:
            self._wkst = wkst
        else:
            self._wkst = wkst.weekday
        if bysetpos is None:
            self._bysetpos = None
        elif type(bysetpos) is int:
            if bysetpos == 0 or not (-366 <= bysetpos <= 366):
                raise ValueError("bysetpos must be between 1 and 366, "
                                 "or between -366 and -1")
            self._bysetpos = (bysetpos,)
        else:
            self._bysetpos = tuple(bysetpos)
            for pos in self._bysetpos:
                if pos == 0 or not (-366 <= pos <= 366):
                    raise ValueError("bysetpos must be between 1 and 366, "
                                     "or between -366 and -1")
        if not (byweekno or byyearday or bymonthday or
                byweekday is not None or byeaster is not None):
            if freq == YEARLY:
                if not bymonth:
                    bymonth = dtstart.month
                bymonthday = dtstart.day
            elif freq == MONTHLY:
                bymonthday = dtstart.day
            elif freq == WEEKLY:
                byweekday = dtstart.weekday()
        # bymonth
        if not bymonth:
            self._bymonth = None
        elif type(bymonth) is int:
            self._bymonth = (bymonth,)
        else:
            self._bymonth = tuple(bymonth)
        # byyearday
        if not byyearday:
            self._byyearday = None
        elif type(byyearday) is int:
            self._byyearday = (byyearday,)
        else:
            self._byyearday = tuple(byyearday)
        # byeaster
        if byeaster is not None:
            if not easter:
                from dateutil import easter
            if type(byeaster) is int:
                self._byeaster = (byeaster,)
            else:
                self._byeaster = tuple(byeaster)
        else:
            self._byeaster = None
        # bymonthay
        if not bymonthday:
            self._bymonthday = ()
            self._bynmonthday = ()
        elif type(bymonthday) is int:
            if bymonthday < 0:
                self._bynmonthday = (bymonthday,)
                self._bymonthday = ()
            else:
                self._bymonthday = (bymonthday,)
                self._bynmonthday = ()
        else:
            self._bymonthday = tuple([x for x in bymonthday if x > 0])
            self._bynmonthday = tuple([x for x in bymonthday if x < 0])
        # byweekno
        if byweekno is None:
            self._byweekno = None
        elif type(byweekno) is int:
            self._byweekno = (byweekno,)
        else:
            self._byweekno = tuple(byweekno)
        # byweekday / bynweekday
        if byweekday is None:
            self._byweekday = None
            self._bynweekday = None
        elif type(byweekday) is int:
            self._byweekday = (byweekday,)
            self._bynweekday = None
        elif hasattr(byweekday, "n"):
            if not byweekday.n or freq > MONTHLY:
                self._byweekday = (byweekday.weekday,)
                self._bynweekday = None
            else:
                self._bynweekday = ((byweekday.weekday, byweekday.n),)
                self._byweekday = None
        else:
            self._byweekday = []
            self._bynweekday = []
            for wday in byweekday:
                if type(wday) is int:
                    self._byweekday.append(wday)
                elif not wday.n or freq > MONTHLY:
                    self._byweekday.append(wday.weekday)
                else:
                    self._bynweekday.append((wday.weekday, wday.n))
            self._byweekday = tuple(self._byweekday)
            self._bynweekday = tuple(self._bynweekday)
            if not self._byweekday:
                self._byweekday = None
            elif not self._bynweekday:
                self._bynweekday = None
        # byhour
        if byhour is None:
            if freq < HOURLY:
                self._byhour = (dtstart.hour,)
            else:
                self._byhour = None
        elif type(byhour) is int:
            self._byhour = (byhour,)
        else:
            self._byhour = tuple(byhour)
        # byminute
        if byminute is None:
            if freq < MINUTELY:
                self._byminute = (dtstart.minute,)
            else:
                self._byminute = None
        elif type(byminute) is int:
            self._byminute = (byminute,)
        else:
            self._byminute = tuple(byminute)
        # bysecond
        if bysecond is None:
            if freq < SECONDLY:
                self._bysecond = (dtstart.second,)
            else:
                self._bysecond = None
        elif type(bysecond) is int:
            self._bysecond = (bysecond,)
        else:
            self._bysecond = tuple(bysecond)

        if self._freq >= HOURLY:
            self._timeset = None
        else:
            self._timeset = []
            for hour in self._byhour:
                for minute in self._byminute:
                    for second in self._bysecond:
                        self._timeset.append(
                                datetime.time(hour, minute, second,
                                                    tzinfo=self._tzinfo))
            self._timeset.sort()
            self._timeset = tuple(self._timeset)
        if normalized_start:
            self.normalize_start()
            
    def normalize_start(self):
        # resets dtstart to match the first instance
        # should this be the default?
        self._dtstart = self.after(self._dtstart, inc=True)
        
    def compare_rrules(self, other):
        return self.repetition_str() == other.repetition_str()

    def repetition_str(self, context=None, original_str=False):
        return self.__unicode__(context=context, mode=REPETITION_ONLY, original_str=original_str)
         
    def fully_resolved_str(self, context=None, original_str=False):
        return self.__unicode__(context=context, mode=FULLY_RESOLVED, original_str=original_str)
         
    def __str__(self, context=None, original_str=False, mode=NORMAL):
        # mode=repetition_only|normal|fully_resolved, original_str=True
        if original_str and self._original_str:
            return self._original_str
        parts = []
        weekdays = []
        DAYS = ['MO','TU','WE','TH','FR','SA','SU']
        if self._byweekday:
            weekdays = [DAYS[day] for day in self._byweekday]
        for name, value in [ # filter out 0s if not mode==FULLY_RESOLVED
                    ('FREQ', [FREQNAMES[self._freq]]),
                    ('WKST', self._wkst),
                    ('COUNT', self._count),
                    ('BYSETPOS', self._bysetpos),
                    ('BYMONTH', self._bymonth),
                    ('BYMONTHDAY', self._bymonthday),
                    ('BYYEARDAY', self._byyearday),
                    ('BYWEEKNO', self._byweekno),
                    ('BYDAY', weekdays),
                    ('BYHOUR', self._byhour),
                    ('BYMINUTE', self._byminute),
                    ('BYSECOND', self._bysecond),
                ]:
            if (mode == FULLY_RESOLVED and value) or name in self.original_params.keys():
                parts.append(name+'='+','.join(str(v) for v in value))
        
        if mode==FULLY_RESOLVED or self._interval != 1:
            parts.append('INTERVAL='+str(self._interval))
        if mode > REPETITION_ONLY and self._until:
            parts.append('UNTIL='+datetime.datetime.strftime(self._until, DATETIME_FORMAT))
        if mode > REPETITION_ONLY and self._dtstart:
            start = 'DTSTART:'+datetime.datetime.strftime(self._dtstart, DATETIME_FORMAT)+'\n'
        else:
            start=''
        if context:
            return '%s%s:%s' % (start, context, ';'.join(parts))
        else:
            return '%s%s' % (start, ';'.join(parts))
   
    def __unicode__(self, context=None, original_str=False, mode=NORMAL):
        return unicode(self.__str__(context=context, original_str=original_str, mode=mode))

    def _iter(self):
        year, month, day, hour, minute, second, weekday, yearday, _ = \
            self._dtstart.timetuple()

        # Some local variables to speed things up a bit
        freq = self._freq
        interval = self._interval
        wkst = self._wkst
        until = self._until
        bymonth = self._bymonth
        byweekno = self._byweekno
        byyearday = self._byyearday
        byweekday = self._byweekday
        byeaster = self._byeaster
        bymonthday = self._bymonthday
        bynmonthday = self._bynmonthday
        bysetpos = self._bysetpos
        byhour = self._byhour
        byminute = self._byminute
        bysecond = self._bysecond

        ii = _iterinfo(self)
        ii.rebuild(year, month)

        getdayset = {YEARLY:ii.ydayset,
                     MONTHLY:ii.mdayset,
                     WEEKLY:ii.wdayset,
                     DAILY:ii.ddayset,
                     HOURLY:ii.ddayset,
                     MINUTELY:ii.ddayset,
                     SECONDLY:ii.ddayset}[freq]
        
        if freq < HOURLY:
            timeset = self._timeset
        else:
            gettimeset = {HOURLY:ii.htimeset,
                          MINUTELY:ii.mtimeset,
                          SECONDLY:ii.stimeset}[freq]
            if ((freq >= HOURLY and
                 self._byhour and hour not in self._byhour) or
                (freq >= MINUTELY and
                 self._byminute and minute not in self._byminute) or
                (freq >= SECONDLY and
                 self._bysecond and second not in self._bysecond)):
                timeset = ()
            else:
                timeset = gettimeset(hour, minute, second)

        total = 0
        count = self._count
        while True:
            # Get dayset with the right frequency
            dayset, start, end = getdayset(year, month, day)

            # Do the "hard" work ;-)
            filtered = False
            for i in dayset[start:end]:
                if ((bymonth and ii.mmask[i] not in bymonth) or
                    (byweekno and not ii.wnomask[i]) or
                    (byweekday and ii.wdaymask[i] not in byweekday) or
                    (ii.nwdaymask and not ii.nwdaymask[i]) or
                    (byeaster and not ii.eastermask[i]) or
                    ((bymonthday or bynmonthday) and
                     ii.mdaymask[i] not in bymonthday and
                     ii.nmdaymask[i] not in bynmonthday) or
                    (byyearday and
                     ((i < ii.yearlen and i+1 not in byyearday
                                      and -ii.yearlen+i not in byyearday) or
                      (i >= ii.yearlen and i+1-ii.yearlen not in byyearday
                                       and -ii.nextyearlen+i-ii.yearlen
                                           not in byyearday)))):
                    dayset[i] = None
                    filtered = True

            # Output results
            if bysetpos and timeset:
                poslist = []
                for pos in bysetpos:
                    if pos < 0:
                        daypos, timepos = divmod(pos, len(timeset))
                    else:
                        daypos, timepos = divmod(pos-1, len(timeset))
                    try:
                        i = [x for x in dayset[start:end]
                                if x is not None][daypos]
                        time = timeset[timepos]
                    except IndexError:
                        pass
                    else:
                        date = datetime.date.fromordinal(ii.yearordinal+i)
                        res = datetime.datetime.combine(date, time)
                        if res not in poslist:
                            poslist.append(res)
                poslist.sort()
                for res in poslist:
                    if until and res > until:
                        self._len = total
                        return
                    elif res >= self._dtstart:
                        total += 1
                        yield res
                        if count:
                            count -= 1
                            if not count:
                                self._len = total
                                return
            else:
                for i in dayset[start:end]:
                    if i is not None:
                        date = datetime.date.fromordinal(ii.yearordinal+i)
                        for time in timeset:
                            res = datetime.datetime.combine(date, time)
                            if until and res > until:
                                self._len = total
                                return
                            elif res >= self._dtstart:
                                total += 1
                                yield res
                                if count:
                                    count -= 1
                                    if not count:
                                        self._len = total
                                        return

            # Handle frequency and interval
            fixday = False
            if freq == YEARLY:
                year += interval
                if year > datetime.MAXYEAR:
                    self._len = total
                    return
                ii.rebuild(year, month)
            elif freq == MONTHLY:
                month += interval
                if month > 12:
                    div, mod = divmod(month, 12)
                    month = mod
                    year += div
                    if month == 0:
                        month = 12
                        year -= 1
                    if year > datetime.MAXYEAR:
                        self._len = total
                        return
                ii.rebuild(year, month)
            elif freq == WEEKLY:
                if wkst > weekday:
                    day += -(weekday+1+(6-wkst))+self._interval*7
                else:
                    day += -(weekday-wkst)+self._interval*7
                weekday = wkst
                fixday = True
            elif freq == DAILY:
                day += interval
                fixday = True
            elif freq == HOURLY:
                if filtered:
                    # Jump to one iteration before next day
                    hour += ((23-hour)//interval)*interval
                while True:
                    hour += interval
                    div, mod = divmod(hour, 24)
                    if div:
                        hour = mod
                        day += div
                        fixday = True
                    if not byhour or hour in byhour:
                        break
                timeset = gettimeset(hour, minute, second)
            elif freq == MINUTELY:
                if filtered:
                    # Jump to one iteration before next day
                    minute += ((1439-(hour*60+minute))//interval)*interval
                while True:
                    minute += interval
                    div, mod = divmod(minute, 60)
                    if div:
                        minute = mod
                        hour += div
                        div, mod = divmod(hour, 24)
                        if div:
                            hour = mod
                            day += div
                            fixday = True
                            filtered = False
                    if ((not byhour or hour in byhour) and
                        (not byminute or minute in byminute)):
                        break
                timeset = gettimeset(hour, minute, second)
            elif freq == SECONDLY:
                if filtered:
                    # Jump to one iteration before next day
                    second += (((86399-(hour*3600+minute*60+second))
                                //interval)*interval)
                while True:
                    second += self._interval
                    div, mod = divmod(second, 60)
                    if div:
                        second = mod
                        minute += div
                        div, mod = divmod(minute, 60)
                        if div:
                            minute = mod
                            hour += div
                            div, mod = divmod(hour, 24)
                            if div:
                                hour = mod
                                day += div
                                fixday = True
                    if ((not byhour or hour in byhour) and
                        (not byminute or minute in byminute) and
                        (not bysecond or second in bysecond)):
                        break
                timeset = gettimeset(hour, minute, second)

            if fixday and day > 28:
                daysinmonth = calendar.monthrange(year, month)[1]
                if day > daysinmonth:
                    while day > daysinmonth:
                        day -= daysinmonth
                        month += 1
                        if month == 13:
                            month = 1
                            year += 1
                            if year > datetime.MAXYEAR:
                                self._len = total
                                return
                        daysinmonth = calendar.monthrange(year, month)[1]
                    ii.rebuild(year, month)

class _iterinfo(object):
    __slots__ = ["rrule", "lastyear", "lastmonth",
                 "yearlen", "nextyearlen", "yearordinal", "yearweekday",
                 "mmask", "mrange", "mdaymask", "nmdaymask",
                 "wdaymask", "wnomask", "nwdaymask", "eastermask"]

    def __init__(self, rrule):
        for attr in self.__slots__:
            setattr(self, attr, None)
        self.rrule = rrule

    def rebuild(self, year, month):
        # Every mask is 7 days longer to handle cross-year weekly periods.
        rr = self.rrule
        if year != self.lastyear:
            self.yearlen = 365+calendar.isleap(year)
            self.nextyearlen = 365+calendar.isleap(year+1)
            firstyday = datetime.date(year, 1, 1)
            self.yearordinal = firstyday.toordinal()
            self.yearweekday = firstyday.weekday()

            wday = datetime.date(year, 1, 1).weekday()
            if self.yearlen == 365:
                self.mmask = M365MASK
                self.mdaymask = MDAY365MASK
                self.nmdaymask = NMDAY365MASK
                self.wdaymask = WDAYMASK[wday:]
                self.mrange = M365RANGE
            else:
                self.mmask = M366MASK
                self.mdaymask = MDAY366MASK
                self.nmdaymask = NMDAY366MASK
                self.wdaymask = WDAYMASK[wday:]
                self.mrange = M366RANGE

            if not rr._byweekno:
                self.wnomask = None
            else:
                self.wnomask = [0]*(self.yearlen+7)
                #no1wkst = firstwkst = self.wdaymask.index(rr._wkst)
                no1wkst = firstwkst = (7-self.yearweekday+rr._wkst)%7
                if no1wkst >= 4:
                    no1wkst = 0
                    # Number of days in the year, plus the days we got
                    # from last year.
                    wyearlen = self.yearlen+(self.yearweekday-rr._wkst)%7
                else:
                    # Number of days in the year, minus the days we
                    # left in last year.
                    wyearlen = self.yearlen-no1wkst
                div, mod = divmod(wyearlen, 7)
                numweeks = div+mod//4
                for n in rr._byweekno:
                    if n < 0:
                        n += numweeks+1
                    if not (0 < n <= numweeks):
                        continue
                    if n > 1:
                        i = no1wkst+(n-1)*7
                        if no1wkst != firstwkst:
                            i -= 7-firstwkst
                    else:
                        i = no1wkst
                    for j in range(7):
                        self.wnomask[i] = 1
                        i += 1
                        if self.wdaymask[i] == rr._wkst:
                            break
                if 1 in rr._byweekno:
                    # Check week number 1 of next year as well
                    # TODO: Check -numweeks for next year.
                    i = no1wkst+numweeks*7
                    if no1wkst != firstwkst:
                        i -= 7-firstwkst
                    if i < self.yearlen:
                        # If week starts in next year, we
                        # don't care about it.
                        for j in range(7):
                            self.wnomask[i] = 1
                            i += 1
                            if self.wdaymask[i] == rr._wkst:
                                break
                if no1wkst:
                    # Check last week number of last year as
                    # well. If no1wkst is 0, either the year
                    # started on week start, or week number 1
                    # got days from last year, so there are no
                    # days from last year's last week number in
                    # this year.
                    if -1 not in rr._byweekno:
                        lyearweekday = datetime.date(year-1,1,1).weekday()
                        lno1wkst = (7-lyearweekday+rr._wkst)%7
                        lyearlen = 365+calendar.isleap(year-1)
                        if lno1wkst >= 4:
                            lno1wkst = 0
                            lnumweeks = 52+(lyearlen+
                                           (lyearweekday-rr._wkst)%7)%7//4
                        else:
                            lnumweeks = 52+(self.yearlen-no1wkst)%7//4
                    else:
                        lnumweeks = -1
                    if lnumweeks in rr._byweekno:
                        for i in range(no1wkst):
                            self.wnomask[i] = 1

        if (rr._bynweekday and
            (month != self.lastmonth or year != self.lastyear)):
            ranges = []
            if rr._freq == YEARLY:
                if rr._bymonth:
                    for month in rr._bymonth:
                        ranges.append(self.mrange[month-1:month+1])
                else:
                    ranges = [(0, self.yearlen)]
            elif rr._freq == MONTHLY:
                ranges = [self.mrange[month-1:month+1]]
            if ranges:
                # Weekly frequency won't get here, so we may not
                # care about cross-year weekly periods.
                self.nwdaymask = [0]*self.yearlen
                for first, last in ranges:
                    last -= 1
                    for wday, n in rr._bynweekday:
                        if n < 0:
                            i = last+(n+1)*7
                            i -= (self.wdaymask[i]-wday)%7
                        else:
                            i = first+(n-1)*7
                            i += (7-self.wdaymask[i]+wday)%7
                        if first <= i <= last:
                            self.nwdaymask[i] = 1

        if rr._byeaster:
            self.eastermask = [0]*(self.yearlen+7)
            eyday = easter.easter(year).toordinal()-self.yearordinal
            for offset in rr._byeaster:
                self.eastermask[eyday+offset] = 1

        self.lastyear = year
        self.lastmonth = month

    def ydayset(self, year, month, day):
        return range(self.yearlen), 0, self.yearlen

    def mdayset(self, year, month, day):
        set = [None]*self.yearlen
        start, end = self.mrange[month-1:month+1]
        for i in range(start, end):
            set[i] = i
        return set, start, end

    def wdayset(self, year, month, day):
        # We need to handle cross-year weeks here.
        set = [None]*(self.yearlen+7)
        i = datetime.date(year, month, day).toordinal()-self.yearordinal
        start = i
        for j in range(7):
            set[i] = i
            i += 1
            #if (not (0 <= i < self.yearlen) or
            #    self.wdaymask[i] == self.rrule._wkst):
            # This will cross the year boundary, if necessary.
            if self.wdaymask[i] == self.rrule._wkst:
                break
        return set, start, i

    def ddayset(self, year, month, day):
        set = [None]*self.yearlen
        i = datetime.date(year, month, day).toordinal()-self.yearordinal
        set[i] = i
        return set, i, i+1

    def htimeset(self, hour, minute, second):
        set = []
        rr = self.rrule
        for minute in rr._byminute:
            for second in rr._bysecond:
                set.append(datetime.time(hour, minute, second,
                                         tzinfo=rr._tzinfo))
        set.sort()
        return set

    def mtimeset(self, hour, minute, second):
        set = []
        rr = self.rrule
        for second in rr._bysecond:
            set.append(datetime.time(hour, minute, second, tzinfo=rr._tzinfo))
        set.sort()
        return set

    def stimeset(self, hour, minute, second):
        return (datetime.time(hour, minute, second,
                tzinfo=self.rrule._tzinfo),)


class DatesHumanizer(HumanizerBase):
    # humanizes a list of rdates
    def __init__(self, datelist, verbosity=NORMAL):
        self.dates = datelist
        self.verbosity = verbosity
        
    def render(self):
        text = []
        for date in self.dates:
            text.append("%s at %s" % (self.render_day(date), self.render_time(date)))
        return ', '.join(text) 
        
class rruleset(rrulebase):

    class _genitem:
        def __init__(self, genlist, gen):
            try:
                self.dt = gen()
                genlist.append(self)
            except StopIteration:
                pass
            self.genlist = genlist
            self.gen = gen

        def next(self):
            try:
                self.dt = self.gen()
            except StopIteration:
                if self.genlist[0] is self:
                    heapq.heappop(self.genlist)
                else:
                    self.genlist.remove(self)
                    heapq.heapify(self.genlist)

        def __cmp__(self, other):
            return cmp(self.dt, other.dt)

    def __init__(self, cache=False, original_str='', match_dtstarts=False):
        rrulebase.__init__(self, cache)
        self._rrule = []
        self._rdate = []
        self._exrule = []
        self._exdate = []
        self.first = None
        self.last = None
        self._original_str = original_str
        self._match_dtstarts = match_dtstarts

    def rrule(self, rrule):
        rrule.normalize_start() # this is not an elegant place to enforce this - needs some design thought
        self._rrule.append(rrule)
        if not self.first or rrule._dtstart < self.first:
            self.first = rrule._dtstart
        if not self.last or not rrule._until or rrule._until > self.last:
            self.last = rrule._until
    
    def rdate(self, rdate):
        if rdate in self._exdate:
            self._exdate.remove(rdate)
        else:
            self._rdate.append(rdate)

    def exrule(self, exrule):
        self._exrule.append(exrule)

    def exdate(self, exdate):
        if exdate in self._rdate:
            self._rdate.remove(exdate)
        else:
            self._exdate.append(exdate)
            

    def _humanize_inclusions(self, verbosity=NORMAL):
        # designed to work on a clustered rruleset, ie. one which has matching dtstarts and no rdates or exdates
        text = []
        for rule in self._rrule:
            text.append(rule.humanize(verbosity=verbosity))
        return '. '.join(text)

    def _humanize_exclusions(self, verbosity=NORMAL):
        # designed to work on a clustered rruleset, ie. one which has matching dtstarts and no rdates or exdates
        text = []
        for exrule in self._exrule:
            exrule_humanizer = RRuleHumanizer(exrule, verbosity=verbosity)
            text.append(exrule_humanizer.render()) # what if multiple rrules and until value differs?
        return '. '.join(text)
    
    def repetition_str(self, original_str=False):
        return self.__unicode__(mode=REPETITION_ONLY, original_str=original_str)
         
    def fully_resolved_str(self, original_str=False):
        return self.__unicode__(mode=FULLY_RESOLVED, original_str=original_str)
         
    def __unicode__(self, original_str=False, mode=NORMAL):
        return unicode(self.__str__(original_str=original_str, mode=mode))

    def __str__(self, original_str=False, mode=NORMAL):
        if original_str and self._original_str:
            return self._original_str
        parts = []
        for rr in self._rrule:
            parts.append(rr.__str__(context='RRULE', mode=mode, original_str=original_str))
        for rd in self._rdate:
            parts.append('RDATE:%s' % datetime.datetime.strftime(rd, DATETIME_FORMAT))
        for xr in self._exrule:
            parts.append(xr.__str__(context='EXRULE', mode=mode, original_str=original_str))
        for xd in self._exdate:
            parts.append('EXDATE:%s' % datetime.datetime.strftime(xd, DATETIME_FORMAT))
        return '\r'.join(parts)
        
    def __unicode__(self, original_str=False, mode=NORMAL):
        return unicode(self.__str__(original_str=original_str, mode=mode))
        
    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, str(self).replace('\r', ' '))

    def count(self):
        for rr in self._rrule:
            if not rr._until and not rr._count:
                return -1
        if not self._len:
            for x in self: pass
        return self._len

    def _iter(self):
        rlist = []
        self._rdate.sort()
        self._genitem(rlist, iter(self._rdate).next)
        for gen in [iter(x).next for x in self._rrule]:
            self._genitem(rlist, gen)
        heapq.heapify(rlist)
        exlist = []
        self._exdate.sort()
        self._genitem(exlist, iter(self._exdate).next)
        for gen in [iter(x).next for x in self._exrule]:
            self._genitem(exlist, gen)
        heapq.heapify(exlist)
        lastdt = None
        total = 0
        while rlist:
            ritem = rlist[0]
            if not lastdt or lastdt != ritem.dt:
#                 if self._match_dtstarts:
#                     while exlist and exlist[0] == ritem:
#                         exitem = exlist[0]
#                         exitem.next()
#                         if exlist and exlist[0] is exitem:
#                             heapq.heapreplace(exlist, exitem)
#                 else:
                while exlist and exlist[0] < ritem:
                    exitem = exlist[0]
                    exitem.next()
                    if exlist and exlist[0] is exitem:
                        heapq.heapreplace(exlist, exitem)
                if not exlist or ritem != exlist[0]:
                    total += 1
                    yield ritem.dt
                lastdt = ritem.dt
            ritem.next()
            if rlist and rlist[0] is ritem:
                heapq.heapreplace(rlist, ritem)
        self._len = total
        
        print "moving instance from %s to %s" % (old_dt, new_dt)
        if old_dt in self:
            if old_dt in self._rdate:
                self._rdate.remove(old_dt)
            else:
                self._exdate.append(old_dt)
        if new_dt not in self:
            if new_dt in self._exdate:
                self._exdate.remove(new_dt)
            else:
                self._rdate.append(new_dt)
            self._rdate.append(new_dt)    

class _rrulestr:

    _freq_map = {"YEARLY": YEARLY,
                 "MONTHLY": MONTHLY,
                 "WEEKLY": WEEKLY,
                 "DAILY": DAILY,
                 "HOURLY": HOURLY,
                 "MINUTELY": MINUTELY,
                 "SECONDLY": SECONDLY}

    _weekday_map = {"MO":0,"TU":1,"WE":2,"TH":3,"FR":4,"SA":5,"SU":6}

    def _handle_int(self, rrkwargs, name, value, **kwargs):
        rrkwargs[name.lower()] = int(value)

    def _handle_int_list(self, rrkwargs, name, value, **kwargs):
        rrkwargs[name.lower()] = [int(x) for x in value.split(',')]

    _handle_INTERVAL   = _handle_int
    _handle_COUNT      = _handle_int
    _handle_BYSETPOS   = _handle_int_list
    _handle_BYMONTH    = _handle_int_list
    _handle_BYMONTHDAY = _handle_int_list
    _handle_BYYEARDAY  = _handle_int_list
    _handle_BYEASTER   = _handle_int_list
    _handle_BYWEEKNO   = _handle_int_list
    _handle_BYHOUR     = _handle_int_list
    _handle_BYMINUTE   = _handle_int_list
    _handle_BYSECOND   = _handle_int_list

    def _handle_FREQ(self, rrkwargs, name, value, **kwargs):
        rrkwargs["freq"] = self._freq_map[value]

    def _handle_UNTIL(self, rrkwargs, name, value, **kwargs):
        global parser
        if not parser:
            from dateutil import parser
        try:
            rrkwargs["until"] = parser.parse(value,
                                           ignoretz=kwargs.get("ignoretz"),
                                           tzinfos=kwargs.get("tzinfos"))
        except ValueError:
            raise ValueError, "invalid until date"

    def _handle_WKST(self, rrkwargs, name, value, **kwargs):
        rrkwargs["wkst"] = self._weekday_map[value]

    def _handle_BYWEEKDAY(self, rrkwargs, name, value, **kwarsg):
        l = []
        for wday in value.split(','):
            for i in range(len(wday)):
                if wday[i] not in '+-0123456789':
                    break
            n = wday[:i] or None
            w = wday[i:]
            if n: n = int(n)
            l.append(weekdays[self._weekday_map[w]](n))
        rrkwargs["byweekday"] = l

    _handle_BYDAY = _handle_BYWEEKDAY

    def _parse_rfc_rrule(self, line,
                         dtstart=None,
                         cache=False,
                         ignoretz=False,
                         tzinfos=None,
                         match_dtstarts=False):
        if line.find(':') != -1:
            name, value = line.split(':')
            if name != "RRULE":
                raise ValueError, "unknown parameter name"
        else:
            value = line
        rrkwargs = {}
        for pair in value.split(';'):
            name, value = pair.split('=')
            name = name.upper()
            value = value.upper()
            try:
                getattr(self, "_handle_"+name)(rrkwargs, name, value,
                                               ignoretz=ignoretz,
                                               tzinfos=tzinfos)
            except AttributeError:
                raise ValueError, "unknown parameter '%s'" % name
            except (KeyError, ValueError):
                raise ValueError, "invalid '%s': %s" % (name, value)
        return rrule(dtstart=dtstart, cache=cache, original_str=line, **rrkwargs)

    def _parse_rfc(self, s,
                   dtstart=None,
                   cache=False,
                   unfold=False,
                   forceset=False,
                   compatible=False,
                   ignoretz=False,
                   tzinfos=None,
                   match_dtstarts=False):
        global parser
        if compatible:
            forceset = True
            unfold = True
        s = s.upper()
        if not s.strip():
            raise ValueError, "empty string"
        if unfold:
            lines = s.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i].rstrip()
                if not line:
                    del lines[i]
                elif i > 0 and line[0] in (" ", "\t"):
                    lines[i-1] += line[1:]
                    del lines[i]
                else:
                    i += 1
        else:
            lines = s.split()
        if (not forceset and len(lines) == 1 and
            (s.find(':') == -1 or s.startswith('RRULE:'))):
            return self._parse_rfc_rrule(lines[0], cache=cache,
                                         dtstart=dtstart, ignoretz=ignoretz,
                                         tzinfos=tzinfos)
        else:
            rrulevals = []
            rdatevals = []
            exrulevals = []
            exdatevals = []
            for line in lines:
                if not line:
                    continue
                if line.find(':') == -1:
                    name = "RRULE"
                    value = line
                else:
                    name, value = line.split(':', 1)
                parms = name.split(';')
                if not parms:
                    raise ValueError, "empty property name"
                name = parms[0]
                parms = parms[1:]
                if name == "RRULE":
                    for parm in parms:
                        raise ValueError, "unsupported RRULE parm: "+parm
                    rrulevals.append((dtstart, value))
                elif name == "RDATE":
                    for parm in parms:
                        if parm != "VALUE=DATE-TIME":
                            raise ValueError, "unsupported RDATE parm: "+parm
                    rdatevals.append(value)
                elif name == "EXRULE":
                    for parm in parms:
                        raise ValueError, "unsupported EXRULE parm: "+parm
                    exrulevals.append((dtstart, value))
                elif name == "EXDATE":
                    for parm in parms:
                        if parm != "VALUE=DATE-TIME":
                            raise ValueError, "unsupported RDATE parm: "+parm
                    exdatevals.append(value)
                elif name == "DTSTART":
                    for parm in parms:
                        raise ValueError, "unsupported DTSTART parm: "+parm
                    if not parser:
                        from dateutil import parser
                    dtstart = parser.parse(value, ignoretz=ignoretz,
                                           tzinfos=tzinfos)
                elif name.upper().startswith('X-'):
                    # Ignore experimental properties.
                    pass
                else:
                    raise ValueError, "unsupported property: "+name
            if (forceset or len(rrulevals) > 1 or
                rdatevals or exrulevals or exdatevals):
                if not parser and (rdatevals or exdatevals):
                    from dateutil import parser
                rrset = rruleset(cache=cache, original_str=s, match_dtstarts=match_dtstarts)
                for value in rrulevals:
                    rrset.rrule(self._parse_rfc_rrule(value[1], dtstart=value[0],
                                                    ignoretz=ignoretz,
                                                    tzinfos=tzinfos,))
                for value in rdatevals:
                    for datestr in value.split(','):
                        rrset.rdate(parser.parse(datestr,
                                               ignoretz=ignoretz,
                                               tzinfos=tzinfos))
                for value in exrulevals:
                    rrset.exrule(self._parse_rfc_rrule(value[1], dtstart=value[0],
                                                     ignoretz=ignoretz,
                                                     tzinfos=tzinfos))
                for value in exdatevals:
                    for datestr in value.split(','):
                        rrset.exdate(parser.parse(datestr,
                                                ignoretz=ignoretz,
                                                tzinfos=tzinfos))
                if compatible and dtstart:
                    rrset.rdate(dtstart)
                return rrset
            else:
                return self._parse_rfc_rrule(rrulevals[0][1],
                                             dtstart=rrulevals[0][0],
                                             cache=cache,
                                             ignoretz=ignoretz,
                                             tzinfos=tzinfos)

    def __call__(self, s, **kwargs):
        return self._parse_rfc(s, **kwargs)

rrulestr = _rrulestr()

# vim:ts=4:sw=4:et
