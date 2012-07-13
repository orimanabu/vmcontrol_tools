#!/usr/bin/env python
# vim: set et sts=4 sw=4 ts=4 :

import os
import sys
import re
import tempfile
import libvirt
import block
from optparse import OptionParser, OptionValueError
from lxml import etree

def get_dumpxml(arg):
    buf = None
    try:
        file = open(arg, 'r')
        buf = file.read()
    except IOError:
        conn = libvirt.openReadOnly(None)
        if conn is None:
            print "libvirt.openReadOnly failed."
            sys.exit(1)
        dom = conn.lookupByName(arg)
        buf = dom.XMLDesc(0)
    return buf

def get_vm_disks(vm):
    xmlstr = get_dumpxml(vm)
    xml = etree.XML(xmlstr)
    disks_elem = xml.xpath("/domain/devices/disk[@device='disk']")
    disks = []
    for disk_elem in disks_elem:
        source = disk_elem.xpath(".//source")[0].attrib['dev']
        realdev = os.path.realpath(source)
        dev = os.stat(realdev).st_rdev
        obj = {'source':os.path.basename(source), 'source_fullpath':source, 'realdev':realdev, 'majmin':(os.major(dev), os.minor(dev))}
        disks.append(obj)
    return disks

def build_majmin2mpath():
    majmin2mpath = {}
    for dev in block.DeviceMaps():
        for dep in dev.deps:
            majmin2mpath[(dep.major, dep.minor)] = dev.name
    return majmin2mpath

def build_majmin2wwn():
    majmin2wwn = {}
    wwn_list = "ls /dev/disk/by-id/wwn-*"
    for wwn_path in os.popen(wwn_list):
        wwn_path = wwn_path.strip()
        dev = os.stat(os.path.realpath(wwn_path)).st_rdev
        majmin2wwn[(os.major(dev), os.minor(dev))] = os.path.basename(wwn_path)
    return majmin2wwn

def update_disks(disks, mpath_flag, wwn_flag):
    for disk in disks:
        if mpath_flag:
            disk['wwn'] = disk['source']
            disk['mpath'] = majmin2mpath[disk['majmin']]
            disk['uuid'] = os.popen("/lib/udev/scsi_id --whitelist --device %s" % disk['source_fullpath']).read().strip()
        if wwn_flag:
            mpath = None
            wwn = None
            uuid = None
            devs = []
            regexp = re.compile('^dm-uuid-mpath-')
            match = regexp.match(disk['source'])
            if match:
                # UUID pattern
                # e.g. "dm-uuid-mpath-3600507680282002010000000000000df"
                uuid = regexp.sub('', disk['source'])
                physdev = os.path.realpath("/dev/disk/by-id/scsi-%s" % uuid)
                dev = os.stat(physdev).st_rdev
                majmin = (os.major(dev), os.minor(dev))
                mpath = majmin2mpath[majmin]
            else:
                # Name pattern
                # e.g. "dm-name-mpathc"
                regexp = re.compile('^dm-name-')
                mpath = regexp.sub('', disk['source'])
            for d,m in majmin2mpath.items():
                if mpath == m:
                    if majmin2wwn.has_key(d):
                        wwn = majmin2wwn[d]
                        break
            disk['wwn'] = wwn
            disk['uuid'] = uuid
            disk['mpath'] = mpath

def check_disks(disks, mpath_flag, wwn_flag):
    if mpath_flag:
        regexp = re.compile('.*mpath.*')
    elif wwn_flag:
        regexp = re.compile('.*wwn-.*')
    for disk in disks:
        m = regexp.match(disk['source'])
        if m:
            print "exit. check whether your option (--mpath or --wwn) is correct."
            sys.exit(1)

def replace_disk(line, disks, mpath_flag, wwn_flag):
    for disk in disks:
        if mpath_flag:
            r = re.compile(disk['wwn'])
#            line = r.sub("dm-name-%s" % disk['mpath'], line)
            line = r.sub("dm-uuid-mpath-%s" % disk['uuid'], line)
        elif wwn_flag:
            if disk['uuid']:
                r = re.compile("dm-uuid-mpath-%s" % disk['uuid'])
                line = r.sub(disk['wwn'], line)
            else:
                r = re.compile("dm-name-%s" % disk['mpath'])
                line = r.sub(disk['wwn'], line)
    return line

majmin2mpath = build_majmin2mpath()
majmin2wwn = build_majmin2wwn()

if __name__ == '__main__':
    usage = "Usage: %s [--wwn | --mpath] [--redefine [--test] | --dumpxml] %s" % (sys.argv[0], "vm")

    parser = OptionParser(usage)
    parser.add_option("-d", "--dumpxml", action="store_true", dest="dumpxml_flag")
    parser.add_option("-r", "--redefine", action="store_true", dest="redefine_flag")
    parser.add_option("-w", "--wwn", action="store_true", dest="wwn_flag")
    parser.add_option("-m", "--mpath", action="store_true", dest="mpath_flag")
    parser.add_option("-t", "--test", action="store_true", dest="test_flag")
    (options, args) = parser.parse_args()

    if not options.mpath_flag and not options.wwn_flag:
        print "needs --mpath or --wwn"
        print usage
        sys.exit(1)

    arg = args[0]
    disks = get_vm_disks(arg)
    check_disks(disks, options.mpath_flag, options.wwn_flag)
    update_disks(disks, options.mpath_flag, options.wwn_flag)

    if options.dumpxml_flag:
        xmlstr = get_dumpxml(arg)
        lines = xmlstr.split('\n')
        for line in lines:
            print replace_disk(line, disks, options.mpath_flag, options.wwn_flag)

    if options.redefine_flag:
        lines = get_dumpxml(arg).split('\n')
        (fd, fname) = tempfile.mkstemp(prefix="vmcontrol_replace_disks_", suffix=".xml")
        print "*** create: %s" % fname
        file = os.fdopen(fd, "w")
        for line in lines:
            print >> file, replace_disk(line, disks, options.mpath_flag, options.wwn_flag)
        file.close()
        virsh_define = "virsh define %s" % fname
        print "*** command:", virsh_define
        if not options.test_flag: os.system(virsh_define)
        print "*** remove: %s" % fname
        if not options.test_flag: os.remove(fname)

    if not options.dumpxml_flag and not options.redefine_flag:
        for disk in disks:
            print "%s\t%s" % (disk['wwn'], disk['mpath'])
