import struct
import unittest

import numpy as np
from ros1_window import Bag, PC2, ns, pointcloud


def fixture(stride=52):
    def u32(v): return struct.pack("<I",v)
    def st(s): return u32(len(s))+s.encode()
    fields=[("x",0,7,1),("y",4,7,1),("z",8,7,1),("intensity",12,7,1),("example",16,4,2)]
    data=bytearray(104)
    for row,col,x in ((0,0,2.),(0,1,0.),(1,0,float("nan")),(1,1,3.)):
        struct.pack_into(">ffffHH",data,row*52+col*20,x,0.,0.,0.,12,770)
    desc=b"".join(st(n)+struct.pack("<IBI",o,t,c) for n,o,t,c in fields)
    return (struct.pack("<III",5,4000000000,123456789)+st("fixture")+struct.pack("<III",2,2,len(fields))+desc+
            struct.pack("<BIII",1,20,stride,len(data))+data+b"\0")


class ReaderTests(unittest.TestCase):
    def test_padded_bigendian_and_vector(self):
        wire=fixture()
        arr,meta=pointcloud(wire)
        self.assertEqual(meta["header_stamp_ns"],"4000000000123456789")
        self.assertEqual((meta["width"],meta["height"],meta["row_step"]),(2,2,52))
        self.assertTrue(meta["is_bigendian"])
        np.testing.assert_array_equal(arr["source_point_index"],[0,1,2,3])
        np.testing.assert_array_equal(arr["valid_mask"],[True,False,False,True])
        np.testing.assert_array_equal(arr["field_4"],np.tile([12,770],(4,1)))
        self.assertEqual(arr["serialized_message"].tobytes(),wire)

    def test_inconsistent_stride(self):
        with self.assertRaises(ValueError):
            pointcloud(fixture(stride=32))

    def test_malformed_nanoseconds(self):
        with self.assertRaises(ValueError):
            ns(struct.pack("<II",1,1_000_000_000))

    def test_mismatch_declared_native_type(self):
        fake=Bag.__new__(Bag)
        fake.connections={0:dict(topic="/example",type="sensor_msgs/PointCloud2",md5sum="wrong")}
        with self.assertRaisesRegex(ValueError,"contract"):
            fake.topic("/example","sensor_msgs/PointCloud2",PC2)


if __name__=="__main__":
    unittest.main()
