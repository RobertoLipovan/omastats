#!/usr/bin/env python3
"""Disk volume regression tests without depending on host storage."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
NAMESPACE = {"__name__": "sampler_test", "__file__": str(ROOT / "sampler.py")}
exec(compile((ROOT / "sampler.py").read_bytes(), "sampler.py", "exec"), NAMESPACE)

MOUNTS = """\
tank/ROOT/root / zfs rw,noatime 0 0
tank/ROOT/home /home zfs rw,noatime 0 0
tank/ROOT/root@daily /.zfs/snapshot/daily zfs ro 0 0
/dev/nvme0n1p1 /boot/efi vfat rw 0 0
"""
ZFS_LIST = "tank\t800\t200\n"
ZPOOL_LIST = "tank\n\tmirror-0\n\t\t/dev/nvme0n1p2\n\t\t/dev/nvme1n1p2\n"


def statvfs(path):
    return SimpleNamespace(f_blocks=1 << 20, f_bfree=1 << 19, f_bavail=1 << 19, f_frsize=4096)


class DiskTests(unittest.TestCase):
    def test_disks_are_identified_by_model_and_serial(self):
        links = [
            ("nvme-eui.0025385991b33317", "nvme1n1"),
            ("nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNF0M921645X_1", "nvme1n1"),
            ("nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNF0M921645X", "nvme1n1"),
            ("nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNF0M921645X-part1", "nvme1n1p1"),
            ("wwn-0x5002538e40e5728a", "sda"),
            ("scsi-SATA_Samsung_SSD_860_S4CYNF0M312756K", "sda"),
            ("ata-Samsung_SSD_860_QVO_2TB_S4CYNF0M312756K", "sda"),
            ("wwn-0x500a0751e2247779", "sdb"),
            ("dm-name-root", "dm-0"),
        ]
        self.assertEqual(NAMESPACE["pick_disk_ids"](links), {
            "nvme1n1": "nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNF0M921645X",
            "sda": "ata-Samsung_SSD_860_QVO_2TB_S4CYNF0M312756K",
            "sdb": "wwn-0x500a0751e2247779",
        })

    def test_shared_sensor_chip_names_are_told_apart_by_device(self):
        sensor_id = NAMESPACE["sensor_id"]
        self.assertEqual(sensor_id({"name": "k10temp", "device": "0000:00:18.3"}, "temp1", False), "k10temp/temp1")
        self.assertEqual(sensor_id({"name": "nvme", "device": "0000:02:00.0"}, "temp1", True), "nvme@0000:02:00.0/temp1")
        self.assertEqual(sensor_id({"name": "nvme", "device": ""}, "temp1", True), "nvme/temp1")

    def test_zpool_leaves_are_first_data_devices(self):
        raw = ZPOOL_LIST + "\nlogs\n\t/dev/sdc1\nfast\n\t/dev/sda1\ncache\n\t/dev/sdd1\n"
        self.assertEqual(NAMESPACE["parse_zpool_leaves"](raw),
                         {"tank": "/dev/nvme0n1p2", "fast": "/dev/sda1"})

    def test_zfs_space_takes_only_plain_byte_counts(self):
        raw = ZFS_LIST + "bad line\nneg\t-5\t1\nsep\t1_000\t1\n"
        self.assertEqual(NAMESPACE["parse_zfs_space"](raw), {"tank": (800, 200)})

    def test_pool_without_zpool_output_keeps_its_space_and_no_drive(self):
        outputs = {"zfs": ZFS_LIST, "zpool": ""}
        sampler = NAMESPACE["DiskSampler"].__new__(NAMESPACE["DiskSampler"])
        with patch("os.statvfs", statvfs), patch.dict(NAMESPACE, {
            "read_text": lambda path, default="": MOUNTS if path == "/proc/self/mounts" else default,
            "run": lambda cmd, timeout=2.0: outputs[cmd[0]],
        }):
            pool = sampler._volumes()[0]
        self.assertEqual((pool["device"], pool["size"], pool["disk"]), ("tank", 1000, ""))

    def test_zfs_datasets_collapse_into_one_pool_volume(self):
        outputs = {"zfs": ZFS_LIST, "zpool": ZPOOL_LIST}
        sampler = NAMESPACE["DiskSampler"].__new__(NAMESPACE["DiskSampler"])
        with patch("os.statvfs", statvfs), patch.dict(NAMESPACE, {
            "read_text": lambda path, default="": MOUNTS if path == "/proc/self/mounts" else default,
            "run": lambda cmd, timeout=2.0: outputs[cmd[0]],
        }), patch.object(NAMESPACE["DiskSampler"], "_parent_disk",
                         staticmethod(lambda device: device.removeprefix("/dev/").removesuffix("p2").removesuffix("p1"))):
            volumes = sampler._volumes()
        self.assertEqual([(v["mount"], v["device"]) for v in volumes],
                         [("/", "tank"), ("/boot/efi", "/dev/nvme0n1p1")])
        pool = volumes[0]
        self.assertEqual((pool["size"], pool["used"], pool["avail"], pool["disk"]),
                         (1000, 800, 200, "nvme0n1"))


if __name__ == "__main__":
    unittest.main()
