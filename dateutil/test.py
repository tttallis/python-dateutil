import unittest
from datetime import datetime
import rrule

class TestRrule(unittest.TestCase):

    def setUp(self):
        self.d1 = datetime(2013,1,1,9,0)
        self.d2 = datetime(2013,1,10,9,0)
        self.d3 = datetime(2013,1,24,11,0)

    def test_rule(self):
        rule = rrule.rrule(dtstart=self.d1, until=self.d2, freq=2)
        x = [
            datetime(2013,1,1,9,0),
            datetime(2013,1,8,9,0),
            datetime(2013,1,15,9,0),
            datetime(2013,1,22,9,0),
        ]
        self.assertEqual(rule[1], x[1])
        
    def test_ruleset(self):
        rule1 = rrule.rrule(dtstart=self.d1, until=self.d2, freq=2)
        rule2 = rrule.rrule(dtstart=self.d3, until=self.d2, freq=2)
    

#         # should raise an exception for an immutable sequence
#         self.assertRaises(TypeError, random.shuffle, (1,2,3))
# 
#     def test_choice(self):
#         element = random.choice(self.seq)
#         self.assertTrue(element in self.seq)
# 
#     def test_sample(self):
#         with self.assertRaises(ValueError):
#             random.sample(self.seq, 20)
#         for element in random.sample(self.seq, 5):
#             self.assertTrue(element in self.seq)

if __name__ == '__main__':
    unittest.main()
