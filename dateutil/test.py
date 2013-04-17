import unittest
from datetime import datetime
import rrule

class TestRrule(unittest.TestCase):

    def setUp(self):
        self.d1 = datetime(2013,1,1,9,0)
        self.d2 = datetime(2013,1,10,11,0)
        self.d3 = datetime(2013,1,24,11,0)
        # terse rrule
        self.text1 = """DTSTART:20130101T090000
                   RRULE:FREQ=WEEKLY;UNTIL=20130124T110000"""
        # equivalent verbose rrule
        self.text2 = """DTSTART:20130101T090000
                   RRULE:FREQ=WEEKLY;BYDAY=TU;BYHOUR=9;BYMINUTE=0;BYSECOND=0;UNTIL=20130124T110000"""
        # fancy rruleset with multiple dtstart
        self.text3 = """DTSTART:20130101T090000
                   RRULE:FREQ=WEEKLY;UNTIL=20130124T110000
                   DTSTART:20130110T110000
                   RRULE:FREQ=WEEKLY;UNTIL=20130124T110000"""
        # extra instance
        self.text4 = """DTSTART:20130101T090000
                   RRULE:FREQ=WEEKLY;UNTIL=20130124T110000
                   DTSTART:20130110T110000
                   RRULE:FREQ=WEEKLY;UNTIL=20130124T110000
                   RDATE:20130101T130000
                   """

    def test_rule(self):
        rule = rrule.rrule(dtstart=self.d1, until=self.d3, freq=2)
        self.assertEqual(rule[1], datetime(2013,1,8,9,0))
        
    def test_ruleset(self):
        rule1 = rrule.rrule(dtstart=self.d1, until=self.d3, freq=2)
        rule2 = rrule.rrule(dtstart=self.d2, until=self.d3, freq=2)
        rs = rrule.rruleset()
        rs.rrule(rule1)
        rs.rrule(rule2)
        self.assertEqual(rs[4], datetime(2013, 1, 17, 11, 0))
#         print repr(rs)
        
    def test_parse(self):
        rule1 = rrule.rrulestr(self.text1)
        rule2 = rrule.rrulestr(self.text2)
        # instances should be same (but may be an empty list I suppose)
        self.assertEqual(list(rule1), list(rule2))
        # check a specific instance
        self.assertEqual(len(list(rule1)), 4)
        
    def test_multi_parse(self):
        rule3 = rrule.rrulestr(self.text3, forceset=True)
        self.assertEquals(len(list(rule3)), 7)
        self.assertEquals(rule3[4], datetime(2013, 1, 17, 11, 0))
    
        rule4 = rrule.rrulestr(self.text4, forceset=True)
        self.assertEquals(len(list(rule4)), 8)
        self.assertEquals(rule4[4], datetime(2013, 1, 15, 9, 0))
        
    def test_exclude_instance(self):
        rule = rrule.rrulestr(self.text4, forceset=True)
        rule.exclude_instance(datetime(2013, 1, 8, 9, 0))
        self.assertEquals(rule[2], datetime(2013, 1, 10, 11, 0))
        # now exclude the extra one
        rule.exclude_instance(datetime(2013, 1, 1, 13, 0))
        self.assertEquals(rule[1], datetime(2013, 1, 10, 11, 0))
        
        rule.move_instance(datetime(2013, 1, 10, 11, 0), datetime(2013, 1, 10, 11, 15))
        self.assertEquals(rule[1], datetime(2013, 1, 10, 11, 15))
        print repr(rule)

if __name__ == '__main__':
    unittest.main()
