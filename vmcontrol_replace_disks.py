#!/usr/bin/env python
# vim: set et sts=4 sw=4 ts=4 :

import os
import sys
import re
import tempfile
from optparse import OptionParser, OptionValueError
from lxml import etree

def get_vm_name(path, args):
    if path:
        file = open(path, 'r')
        xml = etree.parse(file, parser=etree.XMLParser())
        return xml.xpath("/domain/name")[0].text
    else:
        return args[0]

def get_dumpxml(path, vm):
    if path:
        file = open(path, 'r')
    else:
        virsh_dumpxml = "virsh dumpxml %s" % vm
        file = os.popen(virsh_dumpxml)
    return file

def get_vm_disks(path, vm):
    file = get_dumpxml(path, vm)
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
    wwn_list = "ls -l /dev/disk/by-id/wwn-*"
    for wwn_path in wwn_list:
            wwn_file = os.path.basename(wwn_path)
            realpath = os.path.realpath

if __name__ == '__main__':
    usage = "Usage: %s [--sed | --dumpxml] %s" % (sys.argv[0], "vm")

    parser = OptionParser(usage)
    parser.add_option("-s", "--sed", action="store_true", dest="sed_flag")
    parser.add_option("-d", "--dumpxml", action="store_true", dest="dumpxml_flag")
    parser.add_option("-r", "--redefine", action="store_true", dest="redefine_flag")
    parser.add_option("-w", "--wwn", action="store_true", dest="wwn_flag")
    parser.add_option("-m", "--mpath", action="store_true", dest="mpath_flag")
    parser.add_option("-i", "--inputxml", action="store", dest="inputxml")
    (options, args) = parser.parse_args()

    vm = get_vm_name(options.inputxml, args)
    disks = get_vm_disks(options.inputxml, vm)
    dev2mpath = build_dev2mpath()
    wwn2majmin = build_wwn2majmin()

    if options.sed_flag:
        print "sed", 
        for disk in disks:
            print "-e 's|%s|dm-name-%s|'" % (disk['source'], dev2mpath[disk['majmin']]),
        print
        sys.exit(0)

    if options.redefine_flag:
        infile = get_dumpxml(options.inputxml, vm)
        (fd, fname) = tempfile.mkstemp(prefix="vmcontrol_replace_disks_", suffix=".xml")
        print "*** create: %s" % fname
        outfile = os.fdopen(fd, "w")
        if options.mpath_flag:
            for line in infile:
                for disk in disks:
                    r = re.compile(disk['source'])
                    line = r.sub("dm-name-%s" % dev2mpath[disk['majmin']], line)
                outfile.write(line)
            outfile.close()
            virsh_define = "virsh define %s" % fname
            print "*** command:", virsh_define
#            os.system(virsh_define)
            print "*** remove: %s" % fname
#            os.remove(fname)
            sys.exit(0)

    if options.dumpxml_flag:
        file = get_dumpxml(options.inputxml, vm)
        if options.mpath_flag:
            for line in file:
                for disk in disks:
                    r = re.compile(disk['source'])
                    line = r.sub("dm-name-%s" % dev2mpath[disk['majmin']], line)
                print line,
            sys.exit(0)
        if options.wwn_flag:
            for disk in disks:
                print "%s\t%d:%d\t" % (disk['source'], disk['majmin'][0], disk['majmin'][1]),
                physdev = os.path.realpath("/dev/block/%s:%s" % disk['majmin'])
                print physdev
                regexp = re.compile('^dm-name-')
                mpath = regexp.sub('', disk['source'])
                print mpath,
                devs = []
                for d,m in dev2mpath.items():
                    if mpath == m:
                        devs.append(d)
                print devs
            
        sys.exit(0)

    for disk in disks:
        print "%s\t%s" % (disk['source'], dev2mpath[disk['majmin']])
