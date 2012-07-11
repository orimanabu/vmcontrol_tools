#!/usr/bin/env python
# vim: set et sts=4 sw=4 ts=4 :

import os
import sys
import re
from optparse import OptionParser, OptionValueError
from lxml import etree

def get_vm_disks(vm):
	virsh_dumpxml = "virsh dumpxml %s" % vm;
	file = os.popen(virsh_dumpxml)
	xml = etree.parse(file, parser=etree.XMLParser())
	disks_elem = xml.xpath("/domain/devices/disk[@device='disk']")
	disks = []
	for disk_elem in disks_elem:
		wwid_fullpath = disk_elem.xpath(".//source")[0].attrib['dev']
		regexp = re.compile('^.*/');
		wwid = regexp.sub('', wwid_fullpath)
		realdev = os.path.realpath(wwid_fullpath)
		dev = os.stat(realdev).st_rdev
		obj = {'wwid':wwid, 'realdev':realdev, 'majmin':(os.major(dev), os.minor(dev))}
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

if __name__ == '__main__':
	usage = "Usage: %s [--sed | --dumpxml] %s" % (sys.argv[0], "vm")

	parser = OptionParser(usage)
	parser.add_option("-s", "--sed", action="store_true", dest="sed_flag")
	parser.add_option("-d", "--dumpxml", action="store_true", dest="dumpxml_flag")
	parser.add_option("-w", "--wwid", action="store_true", dest="wwid_flag")
	parser.add_option("-m", "--mpath", action="store_true", dest="mpath_flag")
	(options, args) = parser.parse_args()

	if len(args) == 0:
		print usage
		sys.exit(1)

	vm = args[0]
	disks = get_vm_disks(vm)
	dev2mpath = build_dev2mpath()

	if options.sed_flag:
		print "sed", 
		for disk in disks:
			print "-e 's|%s|dm-name-%s|'" % (disk['wwid'], dev2mpath[disk['majmin']]),
		print
		sys.exit(0)

	if options.dumpxml_flag:
		file = os.popen(virsh_dumpxml)
		for line in file:
			for disk in disks:
				r = re.compile(disk['wwid'])
				line = r.sub("dm-name-%s" % dev2mpath[disk['majmin']], line)
			print line,
		sys.exit(0)

	for disk in disks:
		print "%s\t%s" % (disk['wwid'], dev2mpath[disk['majmin']])
