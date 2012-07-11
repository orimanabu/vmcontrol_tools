#!/bin/sh

if [ x"$#" != x"1" ]; then
	echo "$0 vm"
	exit 1
fi
vm=$1; shift

virsh dumpxml ${vm} | eval `python ./vmcontrol_replace_disk.py --sed ${vm}`
