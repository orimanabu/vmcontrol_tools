#!/usr/bin/env python
# vim: set et sts=4 sw=4 ts=4 :

import os
import sys
import re
import tempfile
from optparse import OptionParser, OptionValueError
from lxml import etree

#def get_vm_name(path, args):
#    if path:
#        file = open(path, 'r')
#        xml = etree.parse(file, parser=etree.XMLParser())
#        return xml.xpath("/domain/name")[0].text
#    else:
#        return args[0]
def get_vm_name(arg):
    try:
        file = open(arg, 'r')
        print "** file"
        xml = etree.parse(file, parser=etree.XMLParser())
        return xml.xpath("/domain/name")[0].text
    except IOError:
        print "** vm"
        return args[0]

#def get_dumpxml(path, vm):
#    if path:
#        file = open(path, 'r')
#    else:
#        virsh_dumpxml = "virsh dumpxml %s" % vm
#        file = os.popen(virsh_dumpxml)
#    return file
def get_dumpxml(vm):
    try:
        file = open(vm, 'r')
        print "* file"
    except IOError:
        print "* vm"
        virsh_dumpxml = "virsh dumpxml %s" % vm
        file = os.popen(virsh_dumpxml)
    return file

#def get_vm_disks(path, vm):
#    file = get_dumpxml(path, vm)
def get_vm_disks(vm):
    file = get_dumpxml(vm)
    xml = etree.parse(file, parser=etree.XMLParser())
    disks_elem = xml.xpath("/domain/devices/disk[@device='disk']")
    disks = []
    for disk_elem in disks_elem:
        source = disk_elem.xpath(".//source")[0].attrib['dev']
        realdev = os.path.realpath(source)
        dev = os.stat(realdev).st_rdev
        obj = {'source':os.path.basename(source), 'source_fullpath':source, 'realdev':realdev, 'majmin':(os.major(dev), os.minor(dev))}
        disks.append(obj)
    return disks

def build_dev2mpath():
    dev2mpath = {}
    dmsetup_list = "dmsetup ls | sort"
    for dmlist in os.popen(dmsetup_list):
        # sample output: "mpathd  (253, 0)"
        regexp = re.compile('\s.*$')
        mdev = regexp.sub('', dmlist)

        # get block devs depends on mdev
        dmsetup_deps = "dmsetup deps %s" % mdev
        for dmdeps in os.popen(dmsetup_deps):
            # sample output: "2 dependencies  : (8, 96) (8, 48)"
            regexp = re.compile('^.*: ')
            deps = regexp.sub('', dmdeps.strip());

            regexp = re.compile('^\(.*?\) ?')
            while deps:
                m = regexp.match(deps)
                if m:
                    dep = m.group(0)
                    deps = regexp.sub('', deps)
                    regexp = re.compile('^\((\d+), (\d+)\)')
                    m = regexp.match(dep)
                    majmin = (int(m.group(1)), int(m.group(2)))
                    dev2mpath[majmin] = mdev
    return dev2mpath

def build_wwn2majmin():
    wwn2majmin = {}
    majmin2wwn = {}
    wwn_list = "ls /dev/disk/by-id/wwn-*"
    for wwn_path in os.popen(wwn_list):
        wwn_path = wwn_path.strip()
        wwn_file = os.path.basename(wwn_path)
        physdev = os.path.realpath(wwn_path)
        dev = os.stat(physdev).st_rdev
        wwn2majmin[wwn_file] = (os.major(dev), os.minor(dev))
        majmin2wwn[(os.major(dev), os.minor(dev))] = wwn_file
    return (wwn2majmin, majmin2wwn)

def update_disks(disks):
    for disk in disks:
        if options.mpath_flag:
            disk['wwn'] = disk['source']
            disk['mpath'] = dev2mpath[disk['majmin']]
        if options.wwn_flag:
            physdev = os.path.realpath("/dev/block/%s:%s" % disk['majmin'])
            regexp = re.compile('^dm-name-')
            mpath = regexp.sub('', disk['source'])
            devs = []
            wwn = None
            for d,m in dev2mpath.items():
                if mpath == m:
                    if majmin2wwn.has_key(d):
                        wwn = majmin2wwn[d]
                        break
            disk['wwn'] = wwn
            disk['mpath'] = mpath

if __name__ == '__main__':
    usage = "Usage: %s [--redefine | --dumpxml] %s" % (sys.argv[0], "vm")

    parser = OptionParser(usage)
    parser.add_option("-d", "--dumpxml", action="store_true", dest="dumpxml_flag")
    parser.add_option("-r", "--redefine", action="store_true", dest="redefine_flag")
    parser.add_option("-w", "--wwn", action="store_true", dest="wwn_flag")
    parser.add_option("-m", "--mpath", action="store_true", dest="mpath_flag")
#    parser.add_option("-i", "--inputxml", action="store", dest="inputxml")
    (options, args) = parser.parse_args()

    if not options.mpath_flag and not options.wwn_flag:
        print "needs --mpath or --wwn"
        print usage
        sys.exit(1)

    arg = args[0]
#    vm = get_vm_name(options.inputxml, args)
    vm = get_vm_name(arg)
#    disks = get_vm_disks(options.inputxml, vm)
    disks = get_vm_disks(arg)
    dev2mpath = build_dev2mpath()
    (wwn2majmin, majmin2wwn) = build_wwn2majmin()
    update_disks(disks)

    if options.dumpxml_flag:
        file = get_dumpxml(arg)
        for line in file:
            for disk in disks:
                if options.mpath_flag:
                    r = re.compile(disk['wwn'])
                    line = r.sub("dm-name-%s" % disk['mpath'], line)
                elif options.wwn_flag:
                    r = re.compile("dm-name-%s" % disk['mpath'])
                    line = r.sub(disk['wwn'], line)
            print line,
        sys.exit(0)

    if options.redefine_flag:
#        infile = get_dumpxml(options.inputxml, vm)
        infile = get_dumpxml(arg)
        (fd, fname) = tempfile.mkstemp(prefix="vmcontrol_replace_disks_", suffix=".xml")
        print "*** create: %s" % fname
        outfile = os.fdopen(fd, "w")
        for line in infile:
            for disk in disks:
                if options.mpath_flag:
                    r = re.compile(disk['wwn'])
                    line = r.sub("dm-name-%s" % disk['mpath'], line)
                elif options.wwn_flag:
                    r = re.compile("dm-name-%s" % disk['mpath'])
                    line = r.sub(disk['wwn'], line)
            outfile.write(line)
        outfile.close()
        virsh_define = "virsh define %s" % fname
        print "*** command:", virsh_define
        os.system(virsh_define)
        print "*** remove: %s" % fname
        os.remove(fname)
        sys.exit(0)

    for disk in disks:
        print "%s\t%s" % (disk['wwn'], disk['mpath'])
