#!/usr/bin/env python3
#===========================================================================
#Copyright (c) 2019, The Linux Foundation. All rights reserved.

#Redistribution and use in source and binary forms, with or without
#modification, are permitted provided that the following conditions are
#met:
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above
#      copyright notice, this list of conditions and the following
#      disclaimer in the documentation and/or other materials provided
#      with the distribution.
#    * Neither the name of The Linux Foundation nor the names of its
#      contributors may be used to endorse or promote products derived
#      from this software without specific prior written permission.
#
#THIS SOFTWARE IS PROVIDED "AS IS" AND ANY EXPRESS OR IMPLIED
#WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
#MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NON-INFRINGEMENT
#ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
#BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
#CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
#SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
#BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
#WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
#OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
#IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ===========================================================================*/

import sys,os,getopt
import random,math
import re
import struct
from types import *
from time import sleep

from xml.etree import ElementTree as ET
#from elementtree.ElementTree import ElementTree
from xml.etree.ElementTree import Element, SubElement, Comment, tostring
from xml.dom import minidom

OutputFolder            = ""

LastPartitionBeginsAt = 0
HashInstructions       = {}
tempVar = 5

NumPhyPartitions        = 0
PartitionCollection     = []        # An array of Partition objects. Partition is a hash of information about partition
PhyPartition            = {}        # An array of PartitionCollection objects

MinSectorsNeeded        = 0
# Ex. PhyPartition[0] holds the PartitionCollection that holds all the info for partitions in PHY partition 0

AvailablePartitions = {}
XMLFile = "module_common.py"

ExtendedPartitionBegins= 0
instructions           = []
HashStruct             = {}

StructPartitions       = []
StructAdditionalFields = []
AllPartitions          = {}

PARTITION_SYSTEM_GUID       =  0x3BC93EC9A0004BBA11D2F81FC12A7328
PARTITION_MSFT_RESERVED_GUID=  0xAE1502F02DF97D814DB80B5CE3C9E316
PARTITION_BASIC_DATA_GUID   =  0xC79926B7B668C0874433B9E5EBD0A0A2

SECTOR_SIZE_IN_BYTES = 512   # This can be over ridden in the partition.xml file

PrimaryGPT  = [0]*17408  # This gets redefined later based on SECTOR_SIZE_IN_BYTES This is LBA 0 to 33 (34 sectors total)    (start of disk)
BackupGPT   = [0]*16896  # This gets redefined later based on SECTOR_SIZE_IN_BYTES This is LBA-33 to -1 (33 sectors total)   (end of disk)

EmptyGPT  = [0]*17408  # This gets redefined later based on SECTOR_SIZE_IN_BYTES This is LBA 0 to 33 (34 sectors total)    (start of disk)

PrimaryGPTNumLBAs=len(PrimaryGPT)/SECTOR_SIZE_IN_BYTES
BackupGPTNumLBAs =len(BackupGPT)/SECTOR_SIZE_IN_BYTES

## Note that these HashInstructions are updated by the XML file

HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']        = 64*1024
HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']    = True
HashInstructions['DISK_SIGNATURE']                      = 0x0

MBR         = [0]*SECTOR_SIZE_IN_BYTES
EBR         = [0]*SECTOR_SIZE_IN_BYTES

hash_w       = [{'start_sector':0,'num_sectors':(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES),
                 'end_sector':(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)-1,'physical_partition_number':0,'boundary_num':0,'num_boundaries_covered':1}]
gen_patch = True
NumWPregions = 0

def ShowPartitionExample():
    print("Your \"partition.xml\" file needs to look like something like this below")
    print("\t(i.e. notice the *multiple* physical_partition tags)\n")
    print("<!-- This is physical partition 0 -->")
    print("<physical_partition>")
    print("  <partition label=\"SBL1\" size_in_kb=\"100\" type=\"DEA0BA2C-CBDD-4805-B4F9-F428251C3E98\" filename=\"sbl1.mbn\"/>")
    print("</physical_partition>")
    print(" ")
    print("<!-- This is physical partition 1 -->")
    print("<physical_partition>")
    print("  <partition label=\"SBL2\" size_in_kb=\"200\" type=\"8C6B52AD-8A9E-4398-AD09-AE916E53AE2D\" filename=\"sbl2.mbn\"/>")
    print("</physical_partition>")

def ConvertKBtoSectors(x):
    ## 1KB / SECTOR_SIZE_IN_BYTES normally means return 2 (i.e. with SECTOR_SIZE_IN_BYTES=512)
    ## 2KB / SECTOR_SIZE_IN_BYTES normally means return 4 (i.e. with SECTOR_SIZE_IN_BYTES=512)
    return int((x*1024)/SECTOR_SIZE_IN_BYTES)

def UpdatePatch(StartSector,ByteOffset,PHYPartition,size_in_bytes,szvalue,szfilename,szwhat):
    global PatchesXML
    SubElement(PatchesXML, 'patch', {'start_sector':StartSector, 'byte_offset':ByteOffset,
                                     'physical_partition_number':str(PHYPartition), 'size_in_bytes':str(size_in_bytes),
                                     'value':szvalue, 'filename':szfilename, 'SECTOR_SIZE_IN_BYTES':str(SECTOR_SIZE_IN_BYTES), 'what':szwhat   })


def UpdateRawProgram(RawProgramXML, StartSector, size_in_KB, PHYPartition, file_sector_offset, num_partition_sectors, filename, sparse, label,readbackverify='false', partofsingleimage='false'):
    if StartSector<0:
        szStartSector = "NUM_DISK_SECTORS%d." % StartSector      ## as in NUM_DISK_SECTORS-33 since %d=-33
        szStartByte   = "(%d*NUM_DISK_SECTORS)%d." % (SECTOR_SIZE_IN_BYTES,StartSector*SECTOR_SIZE_IN_BYTES)
    else:
        #print "\nTo be here means StartSector>0"
        #print "UpdateRawProgram StartSector=",StartSector
        #print "StartSector=",type(StartSector)
        #print "-----------------------------------------"

        szStartByte   = str(hex(int(StartSector)*SECTOR_SIZE_IN_BYTES))
        szStartSector = str(StartSector)

    #import pdb; pdb.set_trace()

    if num_partition_sectors<=0:
        #print "*"*78
        #print "WARNING: num_partition_sectors is %d for '%s' PHYPartition=%d, setting it to 0" % (num_partition_sectors,label,PHYPartition)
        #print "\tThis can happen if you only have 1 partition and thus it is the grow partition"
        num_partition_sectors = 0
        size_in_KB = 0

    if erasefirst:
        if label!="cdt":
            SubElement(RawProgramXML, 'erase', {'start_sector':szStartSector, 'physical_partition_number':str(PHYPartition),
                                                'num_partition_sectors':str(num_partition_sectors), 'filename':filename,
                                                'SECTOR_SIZE_IN_BYTES':str(SECTOR_SIZE_IN_BYTES) })


    SubElement(RawProgramXML, 'program', {'start_sector':szStartSector, 'size_in_KB':str(size_in_KB), 'physical_partition_number':str(PHYPartition), 'partofsingleimage':partofsingleimage,
                                          'file_sector_offset':str(file_sector_offset), 'num_partition_sectors':str(num_partition_sectors), 'readbackverify':readbackverify,
                                          'filename':filename,  'sparse':sparse, 'start_byte_hex':szStartByte,  'SECTOR_SIZE_IN_BYTES':str(SECTOR_SIZE_IN_BYTES), 'label':label       })


    #iter = RawProgramXML.getiterator()
    #for element in iter:
    #    print "\nElement:" , element.tag, " : ", element.text   # thins like image,primary,extended etc
    #    if element.keys():
    #        print "\tAttributes:"

    #        for name, value in element.items():
    #            print "\t\tName: '%s'=>'%s' " % (name,value)


    #import pdb; pdb.set_trace()



def PrintBigWarning(sz):
    print("\t                          _             ")
    print("\t                         (_)            ")
    print("\t__      ____ _ _ __ _ __  _ _ __   __ _ ")
    print("\t\\ \\ /\\ / / _` | '__| '_ \\| | '_ \\ / _` |")
    print("\t \\ V  V / (_| | |  | | | | | | | | (_| |")
    print("\t  \\_/\\_/ \\__,_|_|  |_| |_|_|_| |_|\\__, |")
    print("\t                                   __/ |")
    print("\t                                  |___/ \n")

    if len(sz)>0:
        print(sz)

def ValidGUIDForm(GUID):

    if type(GUID) is not str:
        GUID = str(GUID)

    print("Testing if GUID=",GUID)

    m = re.search(r'0x([a-fA-F\d]{32})$', GUID)     #0xC79926B7B668C0874433B9E5EBD0A0A2
    if m is not None:
        return True

    m = re.search(r'([a-fA-F\d]{8})-([a-fA-F\d]{4})-([a-fA-F\d]{4})-([a-fA-F\d]{2})([a-fA-F\d]{2})-([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})', GUID)
    if m is not None:
        return True

    print("GUID does not match regular expression")

    return False

def ValidateTYPE(Type):
    # for type I must support the original "4C" and if they put "0x4C"

    if type(Type) is int:
        if Type>=0 and Type<=255:
            return Type

    if type(Type) is not str:
        Type = str(Type)

    m = re.search(r'^(0x)?([a-fA-F\d][a-fA-F\d]?)$', Type)
    if m is None:
        print("\tWARNING: Type \"%s\" is not in the form 0x4C" % Type)
        sys.exit(1)
    else:
        #print m.group(2)
        #print "---------"
        #print "\tType is \"0x%X\"" % Type
        return int(m.group(2),16)

def ValidateGUID(GUID):

    if type(GUID) is not str:
        GUID = str(GUID)

    print("Looking to validate GUID=",GUID)

    m = re.search(r'0x([a-fA-F\d]{32})$', GUID)     #0xC79926B7B668C0874433B9E5EBD0A0A2
    if m is not None:
        tempGUID = int(m.group(1),16)
        print("\tGUID \"%s\"" % GUID)

        if tempGUID == PARTITION_SYSTEM_GUID:
            print("\tPARTITION_SYSTEM_GUID detected\n")
        elif tempGUID == PARTITION_MSFT_RESERVED_GUID:
            print("\tPARTITION_MSFT_RESERVED_GUID detected\n")
        elif tempGUID == PARTITION_BASIC_DATA_GUID:
            print("\tPARTITION_BASIC_DATA_GUID detected\n")
        else:
            print("\tUNKNOWN PARTITION_GUID detected\n")

        return tempGUID

    else:
        #ebd0a0a2-b9e5-4433-87c0-68b6b72699c7  --> #0x C7 99 26 B7 B6 68 C087 4433 B9E5 EBD0A0A2
        m = re.search(r'([a-fA-F\d]{8})-([a-fA-F\d]{4})-([a-fA-F\d]{4})-([a-fA-F\d]{2})([a-fA-F\d]{2})-([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})([a-fA-F\d]{2})', GUID)
        if m is not None:
            print("Found more advanced type")
            tempGUID = (int(m.group(4),16)<<64) | (int(m.group(3),16)<<48) | (int(m.group(2),16)<<32) | int(m.group(1),16)
            tempGUID|= (int(m.group(8),16)<<96) | (int(m.group(7),16)<<88) | (int(m.group(6),16)<<80) | (int(m.group(5),16)<<72)
            tempGUID|= (int(m.group(11),16)<<120)| (int(m.group(10),16)<<112)| (int(m.group(9),16)<<104)
            print("** CONVERTED GUID \"%s\" is FOUND --> 0x%X" % (GUID,tempGUID))
            return tempGUID
        else:
            print("\nWARNING: "+"-"*78)
            print("*"*78)
            print("WARNING: GUID \"%s\" is not in the form ebd0a0a2-b9e5-4433-87c0-68b6b72699c7" % GUID)
            print("*"*78)
            print("WARNING"+"-"*78+"\n")
            print("Converted to PARTITION_BASIC_DATA_GUID (0xC79926B7B668C0874433B9E5EBD0A0A2)\n")
            return PARTITION_BASIC_DATA_GUID

def EnsureDirectoryExists(filename):
    dir = os.path.dirname(filename)

    try:
        os.stat(dir)
    except:
        os.makedirs(dir)

def WriteGPT(GPTMAIN, GPTBACKUP, GPTEMPTY):
    global opfile,PrimaryGPT,BackupGPT,GPTBOTH
    #for b in PrimaryGPT:
    #    opfile.write(struct.pack("B", b))
    #for b in BackupGPT:
    #    opfile.write(struct.pack("B", b))

    ofile = open(GPTMAIN, "wb")
    for b in PrimaryGPT:
        ofile.write(struct.pack("B", b))
    ofile.close()

    print("\nCreated \"%s\"\t\t\t<-- Primary GPT partition tables + protective MBR" % GPTMAIN)

    ofile = open(GPTBACKUP, "wb")
    for b in BackupGPT:
        ofile.write(struct.pack("B", b))
    ofile.close()

    print("Created \"%s\"\t\t<-- Backup GPT partition tables" % GPTBACKUP)

    ofile = open(GPTBOTH, "wb")
    for b in PrimaryGPT:
        ofile.write(struct.pack("B", b))
    for b in BackupGPT:
        ofile.write(struct.pack("B", b))
    ofile.close()

    print("Created \"%s\" \t\t<-- you can run 'perl parseGPT.pl %s'" % (GPTBOTH,GPTBOTH))

    ## EmptyGPT is just all 0's, let's fill in the correct data
    FillInEmptyGPT()

    ofile = open(GPTEMPTY, "wb")
    for b in EmptyGPT:
        ofile.write(struct.pack("B", b))
    ofile.close()

    print("Created \"%s\"\t\t<-- Empty GPT partition table, use to force EDL mode (very useful)" % GPTEMPTY)

def FillInEmptyGPT():
    global EmptyGPT

    i=SECTOR_SIZE_IN_BYTES+16
    EmptyGPT[0:i]       = PrimaryGPT[0:i]  ## this copies up to EFI PART, REVISION and HEADER SIZE
    EmptyGPT[i:i+4]     = [0xD6, 0x51, 0x5B, 0x44] # CRC32
    i+=8
    EmptyGPT[i:i+1]     = [0x01] # Current LBA
    i+=16
    EmptyGPT[i:i+1]     = [0x22] # First useable LBA
    i+=16
    EmptyGPT[i:i+16]    = [0x32, 0x1B, 0x10, 0x98, 0xE2, 0xBB, 0xF2, 0x4B, 0xA0, 0x6E, 0x2B, 0xB3, 0x3D, 0x00, 0x0C, 0x20] # DISK GUID
    i+=16
    EmptyGPT[i:i+1]     = [0x02] # Starting LBA
    i+=8
    EmptyGPT[i:i+16]    = [0x04, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x04, 0x87, 0x5D, 0x3C, 0x00, 0x00, 0x00, 0x00] # Num Entries, Size of Array, CRC

    i=2*SECTOR_SIZE_IN_BYTES+16
    EmptyGPT[i:i+16]    = [0x6B, 0xCA, 0x1F, 0xEF, 0x31, 0x26, 0xC9, 0x95, 0x5C, 0x13, 0x61, 0xEB, 0x3F, 0xCF, 0x87, 0xF9]  # unique GUID
    i+=16
    EmptyGPT[i:i+1]     = [0x22] # first LBA
    i+=8
    EmptyGPT[i:i+2]     = [0x21, 0x02]  # last LBA
    i+=16
    EmptyGPT[i:i+9]     = [0x65, 0x00, 0x6D, 0x00, 0x70, 0x00, 0x74, 0x00, 0x79]    # unicode "empty" partition name



def UpdatePrimaryGPT(value,length,i):
    global PrimaryGPT
    for b in range(length):
        PrimaryGPT[i] = ((int(value)>>(b*8)) & 0xFF) ; i+=1
    return i

def UpdateBackupGPT(value,length,i):
    global BackupGPT
    for b in range(length):
        BackupGPT[i] = ((int(value)>>(b*8)) & 0xFF) ; i+=1
    return i

def ShowBackupGPT(sector):
    global BackupGPT
    print("Sector: %d" % sector)
    for j in range(32):
        for i in range(16):
            sys.stdout.write("%.2X " % BackupGPT[i+j*16+sector*SECTOR_SIZE_IN_BYTES])
        print(" ")
    print(" ")

def CreateFileOfZeros(filename,num_total_sectors):
    if OutputFolder:
        filename = os.path.join(OutputFolder, filename)
    try:
        opfile = open(filename, "w+b")
    except Exception as x:
        print("ERROR: Could not create '%s', cwd=%s" % (filename,os.getcwd() ))
        print("REASON: %s" % (x))
        sys.exit(1)

    num_sectors = int(num_total_sectors)
    temp = [0]*(SECTOR_SIZE_IN_BYTES*num_sectors)
    zeros = struct.pack("%iB"%(SECTOR_SIZE_IN_BYTES*num_sectors),*temp)
    try:
        opfile.write(zeros)
    except Exception as x:
        print("ERROR: Could not write zeros to '%s'\nREASON: %s" % (filename,x))
        sys.exit(1)

    try:
        opfile.close()
    except Exception as x:
        print("\tWARNING: Could not close %s" % filename)
        print("REASON: %s" % (x))

    print("Created \"%s\"\t\t<-- full of binary zeros - used by \"wipe\" rawprogram files" % filename)

def CreateErasingRawProgramFiles():
    global gen_patch
    CreateFileOfZeros("zeros_1sector.bin",1)
    CreateFileOfZeros("zeros_%dsectors.bin" % BackupGPTNumLBAs,BackupGPTNumLBAs)

    ##import pdb; pdb.set_trace()
    for i in range(8):  # PHY partitions 0 to 7 exist (with 4,5,6,7 as GPPs)
        if i==3:
            continue    # no such PHY partition as of Feb 23, 2012
        temp = Element('data')
        temp.append(Comment('NOTE: This is an ** Autogenerated file **'))
        temp.append(Comment('NOTE: Sector size is %ibytes'%SECTOR_SIZE_IN_BYTES))

        CreateFileOfZeros("zeros_33sectors.bin",33)
        UpdateRawProgram(temp,0, 0.5, i, 0, 1, "zeros_33sectors.bin", "false", "Overwrite MBR sector")
        UpdateRawProgram(temp,1, BackupGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, i, 0, BackupGPTNumLBAs, "zeros_%dsectors.bin" % BackupGPTNumLBAs, "false", "Overwrite Primary GPT Sectors")

        backup_gpt_lba = -BackupGPTNumLBAs
        if gen_patch == True:
            UpdateRawProgram(temp,backup_gpt_lba, BackupGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, i, 0, BackupGPTNumLBAs, "zeros_%dsectors.bin" % BackupGPTNumLBAs, "false", "Overwrite Backup GPT Sectors")

        RAW_PROGRAM = '%swipe_rawprogram_PHY%d.xml' % (OutputFolder,i)

        opfile = open(RAW_PROGRAM, "w")
        opfile.write( prettify(temp) )
        opfile.close()
        print("Created \"%s\"\t<-- Used to *wipe/erase* partition information" % RAW_PROGRAM)


NumPartitions       = 0
SizeOfPartitionArray= 0

def CreateGPTPartitionTable(PhysicalPartitionNumber,UserProvided=False):
    global opfile,PhyPartition,PrimaryGPT,BackupGPT,EmptyGPT,RawProgramXML, GPTMAIN, GPTBACKUP, GPTBOTH, RAW_PROGRAM, PATCHES, PrimaryGPTNumLBAs, BackupGPTNumLBAs
    global gen_patch

    print("\n\nMaking GUID Partitioning Table (GPT)")

    #PrintBanner("instructions")

    #print "\nGoing through partitions listed in XML file"

    ## Step 2. Move through partitions resizing as needed based on WRITE_PROTECT_BOUNDARY_IN_KB

    #print "\n\n--------------------------------------------------------"
    #print "This is the order of the partitions"
    # I most likely need to resize at least one partition below to the WRITE_PROTECT_BOUNDARY_IN_KB boundary
    #for k in range(len(PhyPartition)):

    k = PhysicalPartitionNumber

    GPTMAIN                     = '%sgpt_main%d.bin'        % (OutputFolder,k)
    GPTEMPTY                    = '%sgpt_empty%d.bin'       % (OutputFolder,k)
    GPTBACKUP                   = '%sgpt_backup%d.bin'      % (OutputFolder,k)
    GPTBOTH                     = '%sgpt_both%d.bin'        % (OutputFolder,k)
    RAW_PROGRAM                 = '%srawprogram%d.xml'      % (OutputFolder,k)
    RAW_PROGRAM_WIPE_PARTITIONS = '%srawprogram%d_WIPE_PARTITIONS.xml'% (OutputFolder,k)
    RAW_PROGRAM_BLANK_GPT       = '%srawprogram%d_BLANK_GPT.xml'% (OutputFolder,k)
    PATCHES                     = '%spatch%i.xml'           % (OutputFolder,k)

    #for k in range(1):

    #PrimaryGPT = [0]*(34*SECTOR_SIZE_IN_BYTES)  # This is LBA 0 to 33 (34 sectors total)    (start of disk)
    #BackupGPT  = [0]*(33*SECTOR_SIZE_IN_BYTES)  # This is LBA-33 to -1 (33 sectors total)   (end of disk)
    if SECTOR_SIZE_IN_BYTES==4096:
        PrimaryGPT = [0]*(1*SECTOR_SIZE_IN_BYTES+1*SECTOR_SIZE_IN_BYTES+4*SECTOR_SIZE_IN_BYTES)
        BackupGPT  = [0]*(1*SECTOR_SIZE_IN_BYTES+4*SECTOR_SIZE_IN_BYTES)
        EmptyGPT   = [0]*(1*SECTOR_SIZE_IN_BYTES+1*SECTOR_SIZE_IN_BYTES+4*SECTOR_SIZE_IN_BYTES)
    else:
        PrimaryGPT = [0]*(34*SECTOR_SIZE_IN_BYTES)  # This is LBA 0 to 33 (34 sectors total)    (start of disk)
        BackupGPT  = [0]*(33*SECTOR_SIZE_IN_BYTES)  # This is LBA-33 to -1 (33 sectors total)   (end of disk)
        EmptyGPT   = [0]*(34*SECTOR_SIZE_IN_BYTES)  # This is LBA 0 to 33 (34 sectors total)    (start of disk)


    ## ---------------------------------------------------------------------------------
    ## Step 2. Move through xml definition and figure out partitions sizes
    ## ---------------------------------------------------------------------------------

    PrimaryGPTNumLBAs=int(len(PrimaryGPT)/SECTOR_SIZE_IN_BYTES)
    BackupGPTNumLBAs =int(len(BackupGPT)/SECTOR_SIZE_IN_BYTES)
    i           = 2*SECTOR_SIZE_IN_BYTES    ## partition arrays begin here
    FirstLBA    = PrimaryGPTNumLBAs
    LastLBA     = FirstLBA               ## Make these equal at first

    if HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] is True:
        UpdateWPhash(FirstLBA, 0)   # make sure 1st write protect boundary is setup correctly

    #print "len(PhyPartition)=%d and k=%d" % (len(PhyPartition),k)

    if(k>=len(PhyPartition)):
        if UserProvided==True:
            print("\nERROR: PHY Partition %i of %i not found" % (k,len(PhyPartition)))
            print("\nERROR: PHY Partition %i of %i not found\n\n" % (k,len(PhyPartition)))
            ShowPartitionExample()
            sys.exit()
        else:
            print("\nERROR: PHY Partition %i of %i not found\n\n" % (k,len(PhyPartition)))
            return  ## Automatically trying to do 0 to 7, and some don't exist, which is to be expected

    SectorsTillNextBoundary = 0


    print("\n\nOn PHY Partition %d that has %d partitions" % (k,len(PhyPartition[k])))
    for j in range(len(PhyPartition[k])):
        #print "\nPartition name='%s' (readonly=%s)" % (PhyPartition[k][j]['label'], PhyPartition[k][j]['readonly'])
        #print "\tat sector location %d (%d KB or %.2f MB) and LastLBA=%d" % (FirstLBA,FirstLBA/2,FirstLBA/2048,LastLBA)
        #print "%d of %d with label %s" %(j,len(PhyPartition[k]),PhyPartition[k][j]['label'])

        print("\n"+"="*78)

        PhyPartition[k][j]['size_in_kb'] = int(PhyPartition[k][j]['size_in_kb'])
        print("\n\n%d of %d \"%s\" (readonly=%s) and size=%dKB (%dMB) (%i sectors with %i bytes/sector)" %(j+1, len(PhyPartition[k]), PhyPartition[k][j]['label'], PhyPartition[k][j]['readonly'], PhyPartition[k][j]['size_in_kb'], PhyPartition[k][j]['size_in_kb']/1024, ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb']), SECTOR_SIZE_IN_BYTES))

        if (PhyPartition[k][j]['size_in_kb']*1024)%SECTOR_SIZE_IN_BYTES>0:
            ## Have a remainder, need to round up to next full sector
            TempResult = (PhyPartition[k][j]['size_in_kb']*1024)/SECTOR_SIZE_IN_BYTES
            TempResult +=1
            PhyPartition[k][j]['size_in_kb'] = (TempResult * SECTOR_SIZE_IN_BYTES)/1024

            ##import pdb; pdb.set_trace() ## verifying sizes

        if HashInstructions['PERFORMANCE_BOUNDARY_IN_KB']>0 and HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] is False:
            PrintBigWarning("WARNING: HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'] is %i KB\n\tbut HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] is FALSE!!\n\n" % HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'])
            PrintBigWarning("WARNING: This means partitions will *NOT* be aligned to a HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'] of %i KB !!\n\n" % HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'])
            print("To correct this, partition.xml should look like this\n")
            print("\t<parser_instructions>")
            print("\t\tPERFORMANCE_BOUNDARY_IN_KB = %i" % Partition['PERFORMANCE_BOUNDARY_IN_KB'])
            print("\t\tALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY=true")
            print("\t</parser_instructions>\n\n")

            if HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] is True:
                ## to be here means this partition *must* be on an ALIGN boundary
                print("\tAlignment is to %iKB" % PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB'])
                SectorsTillNextBoundary = ReturnNumSectorsTillBoundary(FirstLBA,PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']) ## hi
                if SectorsTillNextBoundary>0:
                    print("\tSectorsTillNextBoundary=%d, FirstLBA=%d it needs to be moved to be aligned to %d" % (SectorsTillNextBoundary,FirstLBA,FirstLBA + SectorsTillNextBoundary))
                    ##print "\tPhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']=",PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']
                    FirstLBA += SectorsTillNextBoundary
        else:
            if PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']>0:
                print("\tThis partition is *NOT* aligned to a performance boundary\n")

        if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
            SectorsTillNextBoundary = ReturnNumSectorsTillBoundary(FirstLBA,HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'])

        if PhyPartition[k][j]['readonly']=="true":
            ## to be here means this partition is read-only, so see if we need to move the start
            if FirstLBA <= hash_w[NumWPregions]["end_sector"]:
                print("\tWe *don't* need to move FirstLBA (%d) since it's covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"]))
                pass
            else:
                print("\tFirstLBA (%d) is *not* covered by the end of the WP region (%d),\n\tit needs to be moved to be aligned to %d" % (FirstLBA,hash_w[NumWPregions]["end_sector"],FirstLBA + SectorsTillNextBoundary))
                FirstLBA += SectorsTillNextBoundary

        else:
            print("\n\tThis partition is *NOT* readonly")
            ## to be here means this partition is writeable, so see if we need to move the start
            if FirstLBA <= hash_w[NumWPregions]["end_sector"]:
                print("\tWe *need* to move FirstLBA (%d) since it's covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"]))
                print("\nhash_w[NumWPregions]['end_sector']=%i" % hash_w[NumWPregions]["end_sector"]);
                print("FirstLBA=%i\n" %FirstLBA);
                FirstLBA += SectorsTillNextBoundary

                print("\tFirstLBA is now %d" % (FirstLBA))
            else:
                #print "Great, We *don't* need to move FirstLBA (%d) since it's *not* covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"])
                pass

        if (j+1) == len(PhyPartition[k]):
            print("\nTHIS IS THE *LAST* PARTITION")

            if HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] == True and gen_patch == True:

                print("\nMeans patching instructions go here")

                PhyPartition[k][j]['size_in_kb']  = 0 # infinite huge
                print("PhyPartition[k][j]['size_in_kb'] set to 0")
                SectorsRemaining = BackupGPTNumLBAs

                print("LastLBA=",LastLBA)
                print("FirstLBA=",FirstLBA)

                # gpt patch - size of last partition ################################################
                #StartSector         = 2*512+40+j*128        ## i.e. skip sector 0 and 1, then it's offset
                #ByteOffset          = str(StartSector%512)
                #StartSector         = str(int(StartSector / 512))

                StartSector         = 40+j*128        ## i.e. skip sector 0 and 1, then it's offset
                ByteOffset          = str(StartSector%SECTOR_SIZE_IN_BYTES)
                StartSector         = str(2+int(StartSector / SECTOR_SIZE_IN_BYTES))

                BackupStartSector   = 40+j*128
                ByteOffset          = str(BackupStartSector%SECTOR_SIZE_IN_BYTES)
                BackupStartSector   = int(BackupStartSector / SECTOR_SIZE_IN_BYTES)

                ## gpt patch - main gpt partition array
                UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,os.path.basename(GPTMAIN),"Update last partition %d '%s' with actual size in Primary Header." % ((j+1),PhyPartition[k][j]['label']))
                UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,"DISK",              "Update last partition %d '%s' with actual size in Primary Header." % ((j+1),PhyPartition[k][j]['label']))

                ## gpt patch - backup gpt partition array
                UpdatePatch(str(BackupStartSector),    ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,os.path.basename(GPTBACKUP),"Update last partition %d '%s' with actual size in Backup Header." % ((j+1),PhyPartition[k][j]['label']))
                UpdatePatch("NUM_DISK_SECTORS-%d." % (BackupGPTNumLBAs-BackupStartSector),ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,"DISK",                "Update last partition %d '%s' with actual size in Backup Header." % ((j+1),PhyPartition[k][j]['label']))
            elif HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] == True and gen_patch == False:
                print("Ignoring GROW_LAST_PARTITION_TO_FILL_DISK because patching was disabled")

        LastLBA = FirstLBA + ConvertKBtoSectors( PhyPartition[k][j]['size_in_kb'] ) ## increase by num sectors, LastLBA inclusive, so add 1 for size
        LastLBA -= 1  # inclusive, meaning 0 to 3 is 4 sectors

        #import pdb; pdb.set_trace()

        print("\n\tAt sector location %d with size %.2f MB (%d sectors) and LastLBA=%d (0x%X)" % (FirstLBA,PhyPartition[k][j]['size_in_kb']/1024.0,ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb']),LastLBA,int(LastLBA)))

        if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
            AlignedRemainder = FirstLBA % HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'];
            if AlignedRemainder==0:
                print("\tWPB: This partition is ** ALIGNED ** to a %i KB boundary at sector %i (boundary %i)" % (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'],FirstLBA,FirstLBA/(ConvertKBtoSectors(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']))))

        if PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']>0:
            AlignedRemainder = FirstLBA % PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB'];
            if AlignedRemainder==0:
                print("\t"+"-"*78)
                print("\tPERF: This partition is ** ALIGNED ** to a %i KB boundary at sector %i (boundary %i)" % (PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB'],FirstLBA,FirstLBA/(ConvertKBtoSectors(PhyPartition[k][j]['PERFORMANCE_BOUNDARY_IN_KB']))))
                print("\t"+"-"*78)

        if PhyPartition[k][j]['readonly']=="true":
            UpdateWPhash(FirstLBA, ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb']))

        #print Partition.keys()
        #print Partition.has_key("label")
        #print "\tsize %i kB (%.2f MB)" % (PhyPartition[k][j]['size_in_kb'], PhyPartition[k][j]['size_in_kb']/1024)

        PartitionTypeGUID = PhyPartition[k][j]['type']
        print("\nPartitionTypeGUID\t0x%X" % PartitionTypeGUID)

        # If the partition is a multiple of 4, it must start on an LBA boundary of size SECTOR_SIZE_IN_BYTES
#        if j%4==0 :
#            # To be here means the partition number is a multiple of 4, so it must start on
#            # an LBA boundary, i.e. LBA2, LBA3 etc.
#            if i%SECTOR_SIZE_IN_BYTES > 0:
#                print "\tWARNING: Location is %i, need to add %i to offset" % (i, SECTOR_SIZE_IN_BYTES-(i%SECTOR_SIZE_IN_BYTES))
#                i += (SECTOR_SIZE_IN_BYTES-(i%SECTOR_SIZE_IN_BYTES))
#
#            print "\n==============================================================================="
#       print "This partition array entry (%i) is a multiple of 4 and must begin on a boundary of size %i bytes" % (j,SECTOR_SIZE_IN_BYTES)
#            print "This partition array entry is at LBA%i, absolute byte address %i (0x%X)" % (i/SECTOR_SIZE_IN_BYTES,i,i)
#       print "NOTE: LBA0 is protective MBR, LBA1 is Primary GPT Header, LBA2 beginning of Partition Array"
#            print "===============================================================================\n"

        for b in range(16):
            PrimaryGPT[i] = ((PartitionTypeGUID>>(b*8)) & 0xFF) ; i+=1

        # Unique Partition GUID
        if sequentialguid == 1:
            UniquePartitionGUID = j+1
        else:
            if PhyPartition[k][j]['uguid'] != "false":
                UniquePartitionGUID = PhyPartition[k][j]['uguid']
            else:
                UniquePartitionGUID = random.randint(0,2**(128))

        print("UniquePartitionGUID\t0x%X" % UniquePartitionGUID)


        # This HACK section is for verifying with GPARTED, allowing me to put in
        # whatever uniqueGUID that program came up with

        #if j==0:
        #    UniquePartitionGUID = 0x373C17CF53BC7FB149B85A927ED24483
        #elif j==1:
        #    UniquePartitionGUID = 0x1D3C4663FC172F904EC7E0C7A8CF84EC
        #elif j==2:
        #    UniquePartitionGUID = 0x04A9B2AAEF96DAAE465F429D0EF5C6E2
        #else:
        #    UniquePartitionGUID = 0x4D82D027725FD3AE46AF1C5A28944977

        for b in range(16):
            PrimaryGPT[i] = ((UniquePartitionGUID>>(b*8)) & 0xFF) ; i+=1

        # First LBA
        for b in range(8):
            PrimaryGPT[i] = ((int(FirstLBA)>>(b*8)) & 0xFF) ; i+=1

        # Last LBA
        for b in range(8):
            PrimaryGPT[i] = ((int(LastLBA)>>(b*8)) & 0xFF) ; i+=1

        print("**** FirstLBA=%d and LastLBA=%d and size is %i sectors" % (FirstLBA,LastLBA,LastLBA-FirstLBA+1))

        # Attributes
        Attributes = 0x0
        #import pdb; pdb.set_trace()

        if PhyPartition[k][j]['readonly']=="true":
            Attributes |= 1<<60 ## Bit 60 is read only
        if PhyPartition[k][j]['hidden']=="true":
            Attributes |= 1<<62
        if PhyPartition[k][j]['dontautomount']=="true":
            Attributes |= 1<<63
        if PhyPartition[k][j]['system']=="true":
            Attributes |= 1<<0
        if PhyPartition[k][j]['tries_remaining']>0:
            Attributes |= PhyPartition[k][j]['tries_remaining']<<52
        if PhyPartition[k][j]['priority']>0:
            Attributes |= PhyPartition[k][j]['priority']<<48

        print("Attributes\t\t0x%X" % Attributes)

        ##import pdb; pdb.set_trace()

        for b in range(8):
            PrimaryGPT[i] = ((Attributes>>(b*8)) & 0xFF) ; i+=1

        if len(PhyPartition[k][j]['label'])>36:
            print("Label %s is more than 36 characters, therefore it's truncated" % PhyPartition[k][j]['label'])
            PhyPartition[k][j]['label'] = PhyPartition[k][j]['label'][0:36]

        #print "LABEL %s and i=%i" % (PhyPartition[k][j]['label'],i)
        # Partition Name
        for b in PhyPartition[k][j]['label']:
            PrimaryGPT[i] = ord(b) ; i+=1
            PrimaryGPT[i] = 0x00   ; i+=1

        for b in range(36-len(PhyPartition[k][j]['label'])):
            PrimaryGPT[i] = 0x00 ; i+=1
            PrimaryGPT[i] = 0x00 ; i+=1

        #for b in range(2):
        #    PrimaryGPT[i] = 0x00 ; i+=1
        #for b in range(70):
        #    PrimaryGPT[i] = 0x00 ; i+=1

        ##FileToProgram   = ""
        ##FileOffset      = 0
        PartitionLabel  = ""

        ## Default for each partition is no file
        FileToProgram           = [""]
        FileOffset              = [0]
        FilePartitionOffset     = [0]
        FileAppsbin             = ["false"]
        FileSparse              = ["false"]

        if 'filename' in PhyPartition[k][j]:
            ##print "filename exists"
            #print PhyPartition[k][j]['filename']
            #print FileToProgram[0]

        # These are all the default values that should be there, including an empty string possibly for filename
            FileToProgram[0]            = PhyPartition[k][j]['filename'][0]
            FileOffset[0]               = PhyPartition[k][j]['fileoffset'][0]
            FilePartitionOffset[0]      = PhyPartition[k][j]['filepartitionoffset'][0]
            FileAppsbin[0]              = PhyPartition[k][j]['appsbin'][0]
            FileSparse[0]               = PhyPartition[k][j]['sparse'][0]

            for z in range(1,len(PhyPartition[k][j]['filename'])):
                FileToProgram.append( PhyPartition[k][j]['filename'][z] )
                FileOffset.append( PhyPartition[k][j]['fileoffset'][z] )
                FilePartitionOffset.append( PhyPartition[k][j]['filepartitionoffset'][z] )
                FileAppsbin.append( PhyPartition[k][j]['appsbin'][z] )
                FileSparse.append( PhyPartition[k][j]['sparse'][z] )

            #print PhyPartition[k][j]['fileoffset']


        #for z in range(len(FileToProgram)):
        #    print "FileToProgram[",z,"]=",FileToProgram[z]
        #    print "FileOffset[",z,"]=",FileOffset[z]
        #    print " "


        if 'label' in PhyPartition[k][j]:
            PartitionLabel = PhyPartition[k][j]['label']

        for z in range(len(FileToProgram)):
        #print "===============================%i of %i===========================================" % (z,len(FileToProgram))
            #print "File: ",FileToProgram[z]
            #print "Label: ",FileToProgram[z]
            #print "FilePartitionOffset[z]=",FilePartitionOffset[z]
            #print "UpdateRawProgram(RawProgramXML,",(FirstLBA+FilePartitionOffset[z]),",",((LastLBA-FirstLBA)*SECTOR_SIZE_IN_BYTES/1024.0),",",PhysicalPartitionNumber,",",FileOffset[z],",",(LastLBA-FirstLBA-FilePartitionOffset[z]),",",(FileToProgram[z]),",", PartitionLabel,")"
            #print "LastLBA=",LastLBA
            #print "FirstLBA=",FirstLBA
            #print "FilePartitionOffset[z]=",FilePartitionOffset[z]
            UpdateRawProgram(RawProgramXML,
                             FirstLBA+FilePartitionOffset[z], # Start sector
                             ((LastLBA-FirstLBA+1))*SECTOR_SIZE_IN_BYTES/1024.0, # Size in KB
                             PhysicalPartitionNumber,
                             FileOffset[z],
                             LastLBA-FirstLBA+1 - FilePartitionOffset[z], # num_partition_sectors
                             FileToProgram[z],
                             FileSparse[z],
                             PartitionLabel,
                             PhyPartition[k][j]['readbackverify'],
                             PhyPartition[k][j]['partofsingleimage'])
            if (j+1) == len(PhyPartition[k]):
                ## last partition, and if GROW was set to True, it will only have a size of 0
                UpdateRawProgram(RawProgramXML_Wipe,
                                 FirstLBA+FilePartitionOffset[z], #Start Sector
                                 (ConvertKBtoSectors(PhyPartition[k][j]['original_size_in_kb'])+(LastLBA-FirstLBA)+1)*SECTOR_SIZE_IN_BYTES/1024.0, # Size in KB
                                 PhysicalPartitionNumber,
                                 FileOffset[z],
                                 ConvertKBtoSectors(PhyPartition[k][j]['original_size_in_kb'])+LastLBA-FirstLBA+1-FilePartitionOffset[z],
                                 "zeros_33sectors.bin",
                                 "false",
                                 PartitionLabel,
                                 PhyPartition[k][j]['readbackverify'],
                                 PhyPartition[k][j]['partofsingleimage'])
            else:
                UpdateRawProgram(RawProgramXML_Wipe,
                                 FirstLBA+FilePartitionOffset[z], # Start Sector
                                 ((LastLBA-FirstLBA)+1)*SECTOR_SIZE_IN_BYTES/1024.0,  # Size in KB
                                 PhysicalPartitionNumber,
                                 FileOffset[z],
                                 LastLBA-FirstLBA+1-FilePartitionOffset[z], # num_partition_sectors
                                 "zeros_33sectors.bin",
                                 "false",
                                 PartitionLabel,
                                 PhyPartition[k][j]['readbackverify'],
                                 PhyPartition[k][j]['partofsingleimage'])

            if j==0:
                UpdateRawProgram(RawProgramXML_Blank,0, 33*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, FileOffset[z], 33, "gpt_empty%d.bin" % k, "false", "PrimaryGPT", "false", "false")


        LastLBA += 1    ## move to the next free sector, also, 0 to 9 inclusive means it's 10
                        ## so below (LastLBA-FirstLBA) must = 10

        FirstLBA = LastLBA      # getting ready for next partition, FirstLBA is now where we left off


    ## Still working on *this* PHY partition

    ## making protective MBR, all zeros in buffer up until 0x1BE

    i = 0x1BE

    PrimaryGPT[i+0]         = 0x00                  # not bootable
    PrimaryGPT[i+1]         = 0x00                  # head
    PrimaryGPT[i+2]         = 0x01                  # sector
    PrimaryGPT[i+3]         = 0x00                  # cylinder
    PrimaryGPT[i+4]         = 0xEE                  # type
    PrimaryGPT[i+5]         = 0xFF                  # head
    PrimaryGPT[i+6]         = 0xFF                  # sector
    PrimaryGPT[i+7]         = 0xFF                  # cylinder
    PrimaryGPT[i+8:i+8+4]   = [0x01,0x00,0x00,0x00] # starting sector
    PrimaryGPT[i+12:i+12+4] = [0xFF,0xFF,0xFF,0xFF] # starting sector

    PrimaryGPT[440]         = (HashInstructions['DISK_SIGNATURE']>>24)&0xFF
    PrimaryGPT[441]         = (HashInstructions['DISK_SIGNATURE']>>16)&0xFF
    PrimaryGPT[442]         = (HashInstructions['DISK_SIGNATURE']>>8)&0xFF
    PrimaryGPT[443]         = (HashInstructions['DISK_SIGNATURE'])&0xFF

    PrimaryGPT[510:512]     = [0x55,0xAA]           # magic byte for MBR partitioning - always at this location regardless of SECTOR_SIZE_IN_BYTES

    i = SECTOR_SIZE_IN_BYTES
    ## Signature and Revision and HeaderSize i.e. "EFI PART" and 00 00 01 00 and 5C 00 00 00
    PrimaryGPT[i:i+16] = [0x45, 0x46, 0x49, 0x20, 0x50, 0x41, 0x52, 0x54, 0x00, 0x00, 0x01, 0x00, 0x5C, 0x00, 0x00, 0x00] ; i+=16

    header_crc_offset = i
    PrimaryGPT[i:i+4] = [0x00, 0x00, 0x00, 0x00]    ; i+=4  ## CRC is zeroed out till calculated later
    PrimaryGPT[i:i+4] = [0x00, 0x00, 0x00, 0x00]    ; i+=4  ## Reserved, set to 0

    # Update the field that says the LBA of the header, for Primary it is always 1.
    i = UpdatePrimaryGPT(1,8,i)
    LastUseableLBA = LastLBA - 1;
    BackupLBA = LastUseableLBA + BackupGPTNumLBAs
    print("BackupLBA {0} = LastUseableLBA {1} + BackupGPTNumLBAs {2}".format(    BackupLBA, LastUseableLBA , BackupGPTNumLBAs))
    #Update GPT Backup LBA, this field may be updated by patching.
    i = UpdatePrimaryGPT(BackupLBA,8,i)
    FirstLBA  = PrimaryGPTNumLBAs
    i = UpdatePrimaryGPT(FirstLBA,8,i)
    i = UpdatePrimaryGPT(LastUseableLBA,8,i)

    ##print "\n\nBackup GPT is at sector %i" % BackupLBA
    ##print "Last Usable LBA is at sector %i" % (LastLBA)

    DiskGUID = random.randint(0,2**(128))
    i = UpdatePrimaryGPT(DiskGUID,16,i)

    PartitionsLBA = 2
    i = UpdatePrimaryGPT(PartitionsLBA,8,i)

    NumPartitions = (SECTOR_SIZE_IN_BYTES/128)*int(len(PhyPartition[k])/(SECTOR_SIZE_IN_BYTES/128))  # Want a multiple of (SECTOR_SIZE_IN_BYTES) to fill the sector (avoids gdisk warning)
    if (len(PhyPartition[k])%(SECTOR_SIZE_IN_BYTES/128))>0:
        NumPartitions+=(SECTOR_SIZE_IN_BYTES/128)

    if force128partitions == 1:
        print("\n\nGPT table will list 128 partitions instead of ",NumPartitions)
        print("This makes the output compatible with some older test utilities")
        NumPartitions = 128

    i = UpdatePrimaryGPT(NumPartitions,4,i) ## (offset 80) Number of partition entries
    ##NumPartitions = 8    ;   i = UpdatePrimaryGPT(NumPartitions,4,i) ## (offset 80) Number of partition entries
    SizeOfPartitionArray = 128
    i = UpdatePrimaryGPT(SizeOfPartitionArray,4,i) ## (offset 84) Size of partition entries

    ## Now I can calculate the partitions CRC
    print("\n\nCalculating CRC with NumPartitions=%i, SizeOfPartitionArray=%i (bytes each) TOTAL LENGTH %d" % (NumPartitions,SizeOfPartitionArray,NumPartitions*SizeOfPartitionArray));
    ##PartitionsCRC = CalcCRC32(PrimaryGPT[1024:],NumPartitions*SizeOfPartitionArray)  ## Each partition entry is 128 bytes


    PartitionsPerSector = SECTOR_SIZE_IN_BYTES/128  ## 128 bytes per partition

    if NumPartitions>PartitionsPerSector:
        SectorsToCalculateCRCOver = NumPartitions/PartitionsPerSector
        if NumPartitions%PartitionsPerSector:
            SectorsToCalculateCRCOver+=1
    else:
        SectorsToCalculateCRCOver = 1

    PartitionsCRC = CalcCRC32(PrimaryGPT[(2*SECTOR_SIZE_IN_BYTES):],SectorsToCalculateCRCOver * SECTOR_SIZE_IN_BYTES)  ## NAND HACK
    i = UpdatePrimaryGPT(PartitionsCRC,4,i)
    print("\n\nCalculated PARTITION CRC is 0x%.8X" % PartitionsCRC)

    #Compute the CRC over the header.
    CalcHeaderCRC = CalcCRC32(PrimaryGPT[SECTOR_SIZE_IN_BYTES:],92)
    UpdatePrimaryGPT(CalcHeaderCRC,4,SECTOR_SIZE_IN_BYTES+16)


    if gen_patch == True:
        ## gpt patch - main gpt header - last useable lba
        ByteOffset          = str(48)
        StartSector         = str(1)
        BackupStartSector   = str(BackupGPTNumLBAs-1)  ## Want last sector    ##str(32)
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,os.path.basename(GPTMAIN), "Update Primary Header with LastUseableLBA.")
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,"DISK",               "Update Primary Header with LastUseableLBA.")
        UpdatePatch(BackupStartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,os.path.basename(GPTBACKUP), "Update Backup Header with LastUseableLBA.")
        UpdatePatch("NUM_DISK_SECTORS-1.",ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % PrimaryGPTNumLBAs,"DISK",             "Update Backup Header with LastUseableLBA.")

        # gpt patch - location of backup gpt header ##########################################
        ByteOffset          = str(32)
        StartSector         = str(1)
        ## gpt patch - main gpt header
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-1.",os.path.basename(GPTMAIN), "Update Primary Header with BackupGPT Header Location.")
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-1.","DISK",               "Update Primary Header with BackupGPT Header Location.")

        # gpt patch - currentLBA backup header ##########################################
        ByteOffset          = str(24)
        BackupStartSector   = str(BackupGPTNumLBAs-1)  ## Want last sector    ##str(32)
        ## gpt patch - main gpt header
        UpdatePatch(BackupStartSector,    ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-1.",os.path.basename(GPTBACKUP), "Update Backup Header with CurrentLBA.")
        UpdatePatch("NUM_DISK_SECTORS-1.",ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-1.","DISK",                 "Update Backup Header with CurrentLBA.")

        # gpt patch - location of backup gpt header ##########################################
        ByteOffset          = str(72)
        BackupStartSector   = str(BackupGPTNumLBAs-1)  ## Want last sector    ##str(32)

        ## gpt patch - main gpt header
        UpdatePatch(BackupStartSector,   ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % BackupGPTNumLBAs,os.path.basename(GPTBACKUP), "Update Backup Header with Partition Array Location.")
        UpdatePatch("NUM_DISK_SECTORS-1",ByteOffset,PhysicalPartitionNumber,8,"NUM_DISK_SECTORS-%d." % BackupGPTNumLBAs,"DISK",                 "Update Backup Header with Partition Array Location.")

        # gpt patch - Partition Array CRC ################################################
        ByteOffset          = str(88)
        StartSector         = str(1)
        BackupStartSector   = str(BackupGPTNumLBAs-1)  ## Want last sector    ##str(32)

        ## gpt patch - main gpt header
        # Add some patch tag that does nothing to keep XML parsers happy.
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"CRC32(2,%d)" % (NumPartitions*SizeOfPartitionArray),os.path.basename(GPTMAIN), "Update Primary Header with CRC of Partition Array.") # CRC32(start_sector:num_bytes)
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"CRC32(2,%d)" % (NumPartitions*SizeOfPartitionArray),"DISK",               "Update Primary Header with CRC of Partition Array.") # CRC32(start_sector:num_bytes)

        ## gpt patch - backup gpt header
        UpdatePatch(BackupStartSector,    ByteOffset,PhysicalPartitionNumber,4,"CRC32(0,%d)" % (NumPartitions*SizeOfPartitionArray),os.path.basename(GPTBACKUP), "Update Backup Header with CRC of Partition Array.")   # CRC32(start_sector:num_bytes)
        UpdatePatch("NUM_DISK_SECTORS-1.",ByteOffset,PhysicalPartitionNumber,4,"CRC32(NUM_DISK_SECTORS-%d.,%d)" % (BackupGPTNumLBAs,NumPartitions*SizeOfPartitionArray),"DISK",                 "Update Backup Header with CRC of Partition Array.")   # CRC32(start_sector:num_bytes)


    # gpt patch - Header CRC ################################################
    ByteOffset          = str(16)
    StartSector         = str(1)
    BackupStartSector   = str(BackupGPTNumLBAs-1)  ## Want last sector    ##str(32)
    # Add some PATCH entries that have no effect in programming to keep XML parser happy, since they expect to see a <patch
    ## gpt patch - main gpt header
    UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"0",os.path.basename(GPTMAIN), "Zero Out Header CRC in Primary Header.")      # zero out old CRC first
    UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"CRC32(1,92)",os.path.basename(GPTMAIN), "Update Primary Header with CRC of Primary Header.") # CRC32(start_sector:num_bytes)
    if gen_patch == True:
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"0",          "DISK", "Zero Out Header CRC in Primary Header.")      # zero out old CRC first
        UpdatePatch(StartSector,ByteOffset,PhysicalPartitionNumber,4,"CRC32(1,92)","DISK", "Update Primary Header with CRC of Primary Header.") # CRC32(start_sector:num_bytes)

        ## gpt patch - backup gpt header
        #import pdb; pdb.set_trace()
        UpdatePatch(BackupStartSector,ByteOffset,PhysicalPartitionNumber,4,"0",os.path.basename(GPTBACKUP), "Zero Out Header CRC in Backup Header.")      # zero out old CRC first
        UpdatePatch(BackupStartSector,ByteOffset,PhysicalPartitionNumber,4,"CRC32(%s,92)" % BackupStartSector,os.path.basename(GPTBACKUP), "Update Backup Header with CRC of Backup Header.")  # CRC32(start_sector:num_bytes)

        UpdatePatch("NUM_DISK_SECTORS-1.",ByteOffset,PhysicalPartitionNumber,4,"0",           "DISK", "Zero Out Header CRC in Backup Header.")      # zero out old CRC first
        UpdatePatch("NUM_DISK_SECTORS-1.",ByteOffset,PhysicalPartitionNumber,4,"CRC32(NUM_DISK_SECTORS-1.,92)","DISK", "Update Backup Header with CRC of Backup Header.")  # CRC32(start_sector:num_bytes)

    ## now create the backup GPT partitions
    BackupGPT       = [0xFF]*(int(BackupGPTNumLBAs)*SECTOR_SIZE_IN_BYTES)
    BackupGPT[0:]   = PrimaryGPT[2*SECTOR_SIZE_IN_BYTES:]

    ## now create the backup GPT header

    BackupGPT[int(BackupGPTNumLBAs-1)*SECTOR_SIZE_IN_BYTES:int(BackupGPTNumLBAs)*SECTOR_SIZE_IN_BYTES]= PrimaryGPT[1*SECTOR_SIZE_IN_BYTES:2*SECTOR_SIZE_IN_BYTES] ##BackupGPTNumLBAs=33
    #ShowBackupGPT(32)

    ## Need to update CurrentLBA, BackupLBA and then recalc CRC for this header
    i = int(BackupGPTNumLBAs-1)*SECTOR_SIZE_IN_BYTES+8+4+4
    i = UpdateBackupGPT(0, 4, i)  ## zero out CRC for the header, will be computed later.
    i = UpdateBackupGPT(0, 4, i)  ## reserved 4 zeros

    # Update the field that says the LBA of this header.
    i = UpdateBackupGPT(BackupLBA,8,i)
    # Update the field that says the LBA of the other header.
    i = UpdateBackupGPT(1,8,i)

    #print "\n\nBackup GPT is at sector %i" % CurrentLBA
    #print "Last Usable LBA is at sector %i" % (CurrentLBA-33)

    i += 8+8+16
    BackupTableLBA = BackupLBA - BackupGPTNumLBAs + 1
    i = UpdateBackupGPT(BackupTableLBA, 8, i)
    #print "PartitionsLBA = %d (0x%X)" % (PartitionsLBA,PartitionsLBA)

    ##print "\nCalculating CRC for Backup Header"
    CalcHeaderCRC = CalcCRC32(BackupGPT[int(BackupGPTNumLBAs-1)*SECTOR_SIZE_IN_BYTES:],92)
    #print "\nCalcHeaderCRC of BackupGPT is 0x%.8X" % CalcHeaderCRC
    i = int(BackupGPTNumLBAs-1)*SECTOR_SIZE_IN_BYTES+8+4+4
    i = UpdateBackupGPT(CalcHeaderCRC,4,i)  ## zero out CRC

    #ShowBackupGPT(32)

    UpdateRawProgram(RawProgramXML,0,       PrimaryGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, 0, PrimaryGPTNumLBAs, os.path.basename(GPTMAIN), 'false', 'PrimaryGPT','false','true')
    UpdateRawProgram(RawProgramXML_Wipe,0,  1*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, 0,  1, "zeros_33sectors.bin", 'false', 'PrimaryGPT','false','true')
    UpdateRawProgram(RawProgramXML_Wipe,1, BackupGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, 0, BackupGPTNumLBAs, "zeros_%dsectors.bin" % BackupGPTNumLBAs, 'false', 'PrimaryGPT','false','true')

    #print "szStartSector=%s" % szStartSector

    start_gpt_backup_lba = -BackupGPTNumLBAs
    if gen_patch == False:
        start_gpt_backup_lba = BackupTableLBA

    UpdateRawProgram(RawProgramXML,start_gpt_backup_lba,       BackupGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, 0, BackupGPTNumLBAs, os.path.basename(GPTBACKUP), 'false', 'BackupGPT','false','true')
    UpdateRawProgram(RawProgramXML_Wipe,start_gpt_backup_lba, BackupGPTNumLBAs*SECTOR_SIZE_IN_BYTES/1024.0, PhysicalPartitionNumber, 0, BackupGPTNumLBAs, "zeros_%dsectors.bin" % BackupGPTNumLBAs, 'false', 'BackupGPT','false','true')
    ##print "szStartSector=%s" % szStartSector


    WriteGPT(GPTMAIN, GPTBACKUP, GPTEMPTY)

    opfile = open(RAW_PROGRAM, "w")
    opfile.write( prettify(RawProgramXML) )
    opfile.close()
    print("\nCreated \"%s\"\t\t\t<-- YOUR partition information is HERE" % RAW_PROGRAM)

    opfile = open(RAW_PROGRAM_WIPE_PARTITIONS, "w")
    opfile.write( prettify(RawProgramXML_Wipe) )
    opfile.close()
    print("Created \"%s\"\t<-- Wipe out your images with this file (if needed for testing)" % RAW_PROGRAM_WIPE_PARTITIONS)

    opfile = open(RAW_PROGRAM_BLANK_GPT, "w")
    opfile.write( prettify(RawProgramXML_Blank) )
    opfile.close()
    print("Created \"%s\"\t\t<-- Valid empty GPT partition table (to force to EDL)" % RAW_PROGRAM_BLANK_GPT)

    opfile = open(PATCHES, "w")             # gpt
    opfile.write( prettify(PatchesXML) )
    opfile.close()
    print("Created \"%s\"\t\t\t\t<-- Tailor your partition tables to YOUR device with this file\n" % PATCHES)



def AlignVariablesToEqualSigns(sz):
    temp = re.sub(r"(\t| )+=","=",sz)
    temp = re.sub(r"=(\t| )+","=",temp)
    return temp

def ReturnArrayFromSpaceSeparatedList(sz):
    temp = re.sub(r"\s+|\n"," ",sz)
    temp = re.sub(r"^\s+","",temp)
    temp = re.sub(r"\s+$","",temp)
    return temp.split(' ')

def ParseXML(XMLFile):
    global OutputToCreate,NumPhyPartitions, PartitionCollection, PhyPartition,MinSectorsNeeded,SECTOR_SIZE_IN_BYTES

    root = ET.parse( XMLFile )

    #Create an iterator
    iter = list(root.iter())

    for element in iter:
        #print "\nElement:" , element.tag   # thins like image,primary,extended etc

        if element.tag=="parser_instructions":
            instructions = ReturnArrayFromSpaceSeparatedList(AlignVariablesToEqualSigns(element.text))

            for element in instructions:
                temp = element.split('=')
                if len(temp) > 1:
                    HashInstructions[temp[0].strip()] = temp[1].strip()
                    #print "HashInstructions['%s'] = %s" % (temp[0].strip(),temp[1].strip())


    if 'SECTOR_SIZE_IN_BYTES' in HashInstructions:
        if type(HashInstructions['SECTOR_SIZE_IN_BYTES']) is str:
            m = re.search(r'^(\d+)$', HashInstructions['SECTOR_SIZE_IN_BYTES'])
            if m is None:
                ## we didn't match, so assign deafult
                HashInstructions['SECTOR_SIZE_IN_BYTES'] = 512
                SECTOR_SIZE_IN_BYTES = 512
            else:
                HashInstructions['SECTOR_SIZE_IN_BYTES'] = int(HashInstructions['SECTOR_SIZE_IN_BYTES'])
                SECTOR_SIZE_IN_BYTES = HashInstructions['SECTOR_SIZE_IN_BYTES']

                PrintBigWarning("WARNING: SECTOR_SIZE_IN_BYTES CHANGED <-- This may impact your targets ability to read the partition tables!!")
                print("\n\nWARNING: SECTOR_SIZE_IN_BYTES *changed* from 512bytes/sector to %ibytes/sector" % SECTOR_SIZE_IN_BYTES)
                print("WARNING: SECTOR_SIZE_IN_BYTES *changed* from 512bytes/sector to %ibytes/sector" % SECTOR_SIZE_IN_BYTES)
                print("WARNING: SECTOR_SIZE_IN_BYTES *changed* from 512bytes/sector to %ibytes/sector\n\n" % SECTOR_SIZE_IN_BYTES)
                sleep(2)
    else:
        #print "SECTOR_SIZE_IN_BYTES does not exist"
        HashInstructions['SECTOR_SIZE_IN_BYTES'] = 512


    if 'WRITE_PROTECT_BOUNDARY_IN_KB' in HashInstructions:
        if type(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']) is str:
            m = re.search(r'^(\d+)$', HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'])
            if m is None:
                ## we didn't match, so assign deafult
                HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'] = 0
            else:
                HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'] = int(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'])
    else:
        #print "WRITE_PROTECT_BOUNDARY_IN_KB does not exist"
        HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'] = 65536

    if 'PERFORMANCE_BOUNDARY_IN_KB' in HashInstructions:
        if type(HashInstructions['PERFORMANCE_BOUNDARY_IN_KB']) is str:
            m = re.search(r'^(\d+)$', HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'])
            if m is None:
                ## we didn't match, so assign deafult
                HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'] = 0
            else:
                HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'] = int(HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'])
    else:
        #print "PERFORMANCE_BOUNDARY_IN_KB does not exist"
        HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'] = 0

    if 'GROW_LAST_PARTITION_TO_FILL_DISK' in HashInstructions:
        if type(HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']) is str:
            m = re.search("^(true)$", HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] ,re.IGNORECASE)
            #print type(m)
            if m is None:
                HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] = False    # no match
                #print "assigned false"
            else:
                HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] = True     # matched string true
                #print "assigned true"
    else:
        HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] = False

    if 'WRITE_PROTECT_GPT_PARTITION_TABLE' in HashInstructions:
        if type(HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE']) is str:
            m = re.search("^(true)$", HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] ,re.IGNORECASE)
            #print type(m)
            if m is None:
                HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] = False    # no match
                #print "assigned false"
            else:
                HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] = True     # matched string true
                #print "assigned true"
    else:
        HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] = False

    if 'ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY' in HashInstructions:
        if type(HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY']) is str:
            m = re.search("^(true)$", HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] ,re.IGNORECASE)
            #print type(m)
            if m is None:
                HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] = False    # no match
                #print "assigned false"
            else:
                HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] = True     # matched string true
                #print "assigned true"
    else:
        HashInstructions['ALIGN_PARTITIONS_TO_PERFORMANCE_BOUNDARY'] = False

    if 'USE_GPT_PARTITIONING' in HashInstructions:
        if type(HashInstructions['USE_GPT_PARTITIONING']) is str:
            m = re.search("^(true)$", HashInstructions['USE_GPT_PARTITIONING'] ,re.IGNORECASE)
            #print type(m)
            if m is None:
                HashInstructions['USE_GPT_PARTITIONING'] = False    # no match
                #print "assigned false"
            else:
                HashInstructions['USE_GPT_PARTITIONING'] = True     # matched string true
                #print "assigned true"
    else:
        HashInstructions['USE_GPT_PARTITIONING'] = False


    if 'DISK_SIGNATURE' in HashInstructions:
        if type(HashInstructions['DISK_SIGNATURE']) is str:
            m = re.search(r'^0x([\da-fA-F]+)$', HashInstructions['DISK_SIGNATURE'])
            if m is None:
                print("WARNING: DISK_SIGNATURE is not formed correctly, expected format is 0x12345678\n")
                HashInstructions['DISK_SIGNATURE'] = 0x00000000
            else:
                HashInstructions['DISK_SIGNATURE'] = int(HashInstructions['DISK_SIGNATURE'],16)
    else:
        print("DISK_SIGNATURE does not exist")
        HashInstructions['DISK_SIGNATURE'] = 0x00000000

    if 'ALIGN_BOUNDARY_IN_KB' in HashInstructions:
        if type(HashInstructions['ALIGN_BOUNDARY_IN_KB']) is str:
            m = re.search(r'^(\d+)$', HashInstructions['ALIGN_BOUNDARY_IN_KB'])
            if m is None:
                ## we didn't match, so assign deafult
                HashInstructions['ALIGN_BOUNDARY_IN_KB'] = HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']
            else:
                HashInstructions['ALIGN_BOUNDARY_IN_KB'] = int(HashInstructions['ALIGN_BOUNDARY_IN_KB'])
    else:
        #print "ALIGN_BOUNDARY_IN_KB does not exist"
        HashInstructions['ALIGN_BOUNDARY_IN_KB'] = HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']

    root = ET.parse( XMLFile )

    #Create an iterator
    iter = list(root.iter())

    ## Need to count how many partitions
    CheckPartitionCount = [0,0,0,0,0,0,0,0]
    CurrentPartition    = -1

    for element in iter:
        ##print "\nElement:" , element.tag   # thins like image,primary,extended etc
        if element.tag == "physical_partition":
            CurrentPartition+=1
            #print "Now on CurrentPartition=",CurrentPartition
        if element.tag == "partition":
            CheckPartitionCount[CurrentPartition] += 1
            #print "CheckPartitionCount[%d]=%d" % (CurrentPartition,CheckPartitionCount[CurrentPartition])

    for p in range(CurrentPartition+1):
        print("CheckPartitionCount[%d]=%d" % (p,CheckPartitionCount[p]))

    CurrentPartition    = -1
    for element in iter:
        #print "\nElement:" , element.tag   # thins like image,primary,extended etc

        if element.tag=="physical_partition":
            # We can have this scenario meaning NumPhyPartitions++ but len(PhyPartition) doesn't increase
            # <physical_partition>
            # </physical_partition>
            # Thus if NumPhyPartitions > len(PhyPartition) by 2, then we need to increase it

            NumPhyPartitions            += 1
            CurrentPartition            = 0 ## Using this to count partitions

            PartitionCollection          = []    # Reset, we've found a new physical partition

            if NumPhyPartitions-len(PhyPartition)>=2:
                print("\n\n")
                print("*"*78)
                print("ERROR: Empty <physical_partition></physical_partition> tags detected\n")
                print("Please replace with")
                print("<physical_partition>")
                print("<partition label='placeholder' size_in_kb='0' type='00000000-0000-0000-0000-000000000001' bootable='false' readonly='false' filename='' />")
                print("</physical_partition>\n")
                sys.exit()

            print("\nFound a physical_partition, NumPhyPartitions=%d" % NumPhyPartitions)
            print("\nlen(PhyPartition)=%d" % len(PhyPartition))


        elif element.tag=="partition" or element.tag=="primary" or element.tag=="extended":

            CurrentPartition+=1

            if list(element.keys()):
                #print "\tAttributes:"

                # Reset all variables to defaults
                Partition = {}

                # This partition could have more than 1 file, so these are arrays
                # However, as I loop through the elements, *if* there is more than 1 file
                # it will have it's own <file> tag
                Partition['filename']            = [""]
                Partition['fileoffset']          = [0]
                Partition['appsbin']             = ["false"]
                Partition['sparse']              = ["false"]
                Partition['filepartitionoffset'] = [0]

                Partition['size_in_kb']         = 0
                Partition['original_size_in_kb']= 0
                Partition['readonly']           = "false"
                Partition['label']              = "false"
                Partition['type']               = "false"
                Partition['uguid']              = "false"   ## unique guid
                Partition['align']              = "false"
                Partition['hidden']             = "false"
                Partition['system']             = "false"
                Partition['dontautomount']      = "false"
                Partition['partofsingleimage']  = "false"
                Partition['readbackverify']     = "false"
                Partition['tries_remaining']    = 0
                Partition['priority']           = 0

                ##import pdb; pdb.set_trace()

                if 'PERFORMANCE_BOUNDARY_IN_KB' in HashInstructions:
                    Partition['PERFORMANCE_BOUNDARY_IN_KB']  = int(HashInstructions['PERFORMANCE_BOUNDARY_IN_KB'])
                else:
                    Partition['PERFORMANCE_BOUNDARY_IN_KB']  = 0

                FileFound = 0

                print(" ")

                for name, value in list(element.items()):
                    #print "\t\tName: '%s'=>'%s' " % (name,value)

                    if name=='name' or name=='filename' :
                        Partition['filename'][-1] = value
                        FileFound = 1
                        print("Found a file tag '%s'" % value)
                    elif name=='fileoffset':
                        Partition['fileoffset'][-1] = value
                    elif name=='label':
                        Partition['label'] = value
                        print("LABEL:",value)
                    elif name=='offset' or name=='filepartitionoffset':
                        Partition['filepartitionoffset'][-1] = int(value)
                    elif name=='appsbin':
                        Partition['appsbin'][-1] = value
                    elif name=='sparse':
                        Partition['sparse'][-1] = value
                    elif name=='PERFORMANCE_BOUNDARY_IN_KB':
                        Partition['PERFORMANCE_BOUNDARY_IN_KB'] = int(value)
                    elif name=='type':
                        if ValidGUIDForm(value) is True:
                            if OutputToCreate is None:
                                OutputToCreate = "gpt"
                            elif OutputToCreate == "mbr":
                                PrintBigError("ERROR: Your partition.xml is possibly corrupt, please check the GUID TYPE field")
                            Partition['type'] = ValidateGUID(value)
                        else:
                            if OutputToCreate is None:
                                OutputToCreate = "mbr"
                            elif OutputToCreate == "gpt":
                                PrintBigError("ERROR: Your partition.xml is possibly corrupt, please check the TYPE field")
                            Partition['type'] = ValidateTYPE(value)
                    elif name=='uniqueguid':
                        if ValidGUIDForm(value) is True:
                            Partition['uguid'] = ValidateGUID(value)
                        else:
                            PrintBigError("ERROR: Your partition.xml is possibly corrupt, please check the TYPE field")
                    elif name=="triesremaining":
                        Partition['tries_remaining'] = int(value);
                    elif name=="priority":
                        Partition['priority']       = int(value);
                    elif name=="size":
                        if len(value)==0:
                            PrintBigError("\nERROR: Invalid partition size")

                        ## 'size' means in terms of sectors
                        TempSizeInBytes = int(value)/2        # force as even number
                        if TempSizeInBytes<2:
                            TempSizeInBytes = 2
                        TempSizeInBytes = TempSizeInBytes*SECTOR_SIZE_IN_BYTES  ## either 1K or 8K

                        Partition["size_in_kb"]=TempSizeInBytes/1024
                        Partition["original_size_in_kb"]=TempSizeInBytes/1024
                    elif name=="size_in_kb":
                        if len(value)==0:
                            PrintBigError("\nERROR: Invalid partition size")


                        if value=='0':
                            if CheckPartitionCount[NumPhyPartitions-1] == CurrentPartition:
                                ## To be here means they have size_in_kb='0' BUT this is ok since it is the LAST partition
                                pass
                            else:
                                PrintBigError("\nERROR: Invalid size_in_kb='0' detected on partition %d of %d. This is usually a mistake. Did you mean this to be the *last* partition"%(CurrentPartition,CheckPartitionCount[NumPhyPartitions-1]))

##timmy

                        TempSizeInBytes = int(value)*1024
                        if TempSizeInBytes < SECTOR_SIZE_IN_BYTES:
                            ## smaller than a sector, which is possible if sector size is 4KB
                            TempSizeInBytes = SECTOR_SIZE_IN_BYTES
                        Partition["size_in_kb"]=TempSizeInBytes/1024
                        Partition["original_size_in_kb"]=TempSizeInBytes/1024

                    else:
                        print("Just assigned %s to %s" % (name,value))
                        Partition[name]=value

        # No longer appending blank filename data for Trace32. Programming based on Label now
                #if FileFound == 1:
                #    Partition['filename'].append("")
                #    Partition['fileoffset'].append(0)
                #    Partition['filepartitionoffset'].append(0)
                #    Partition['appsbin'].append("false")
                #    Partition['sparse'].append("false")



                ## done with all the elements, now ensure that size matches with size_in_kb
                Partition["size"] = ConvertKBtoSectors(Partition["size_in_kb"]) # Still 512 bytes/sector here since "size" is a legacy field

                ## Now add this "Partition" object to the PartitionCollection
                ## unless it's the label EXT, which is a left over legacy tag

                if Partition['label'] != 'EXT':
                    #print "\nJust added %s" % Partition['label']
                    PartitionCollection.append( Partition )

                    print("="*40)
                    print("storing at %d" % (NumPhyPartitions-1))
                    ##import pdb; pdb.set_trace()

                    print("Adding PartitionCollection to \"PhyPartition\" of size %i" % (NumPhyPartitions-1))
                    PhyPartition[(NumPhyPartitions-1)]          = PartitionCollection

                    #print "\nPartition stored (%i partitions total)" % len(PartitionCollection)

            else:
                PrintBigError("ERROR: element.tag was partition, primary or extended, but it had no keys!")

        elif element.tag=="file":
            #print "element.tag=='file' Found a file, NumPhyPartitions=",NumPhyPartitions    ## i.e. just a file tag (usually in legacy)
            #print PhyPartition[(NumPhyPartitions-1)]
            #print "Current partition is \"%s\"\n" % Partition['label']

            if list(element.keys()):
                for name, value in list(element.items()):
                    if name=='name' or name=='filename' :
                        Partition['filename'][-1] = value
                    if name=='fileoffset':
                        Partition['fileoffset'][-1] = value
                    if name=='offset' or name=='filepartitionoffset':
                        Partition['filepartitionoffset'][-1] = int(value)
                    if name=='appsbin':
                        Partition['appsbin'][-1] = value
                    if name=='sparse':
                        Partition['sparse'][-1] = value

                    #Partition[name]=value

            #print Partition['filename']
            Partition['filename'].append("")
            Partition['fileoffset'].append(0)
            Partition['filepartitionoffset'].append(0)
            Partition['appsbin'].append("false")
            Partition['sparse'].append("false")

        #try:
        #    if len(Partition['filename'])>1:
        #        print "="*78
        #        print "="*78
        #        for z in range(len(Partition['filename'])):
        #            print "Partition['filename'][",z,"]=",Partition['filename'][z]
        #            print "Partition['fileoffset'][",z,"]=",Partition['fileoffset'][z]
        #            print "Partition['filepartitionoffset'][",z,"]=",Partition['filepartitionoffset'][z]
        #            print "Partition['appsbin'][",z,"]=",Partition['appsbin'][z]
        #            print "Partition['sparse'][",z,"]=",Partition['sparse'][z]
        #            print "-"*78
        #        print "="*78
        #except:
        #    print " "
        #print "Showing the changes to PartitionCollection"
        #print PartitionCollection[-1]


    # Must update this if the user has updated WRITE_PROTECT_BOUNDARY_IN_KB in partition.xml
    hash_w[NumWPregions]['num_sectors'] = (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)
    hash_w[NumWPregions]['end_sector']  = (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)-1

    if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'] == 0:
        hash_w[NumWPregions]['num_sectors']             = 0
        hash_w[NumWPregions]['end_sector']              = 0
        hash_w[NumWPregions]['num_boundaries_covered']  = 0

    if OutputToCreate == "gpt" and HashInstructions['WRITE_PROTECT_GPT_PARTITION_TABLE'] is False:
        hash_w[NumWPregions]['num_sectors']             = 0
        hash_w[NumWPregions]['end_sector']              = 0
        hash_w[NumWPregions]['num_boundaries_covered']  = 0

    print("HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']    =%d" % HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'])
    print("HashInstructions['ALIGN_BOUNDARY_IN_KB']            =%d" % HashInstructions['ALIGN_BOUNDARY_IN_KB'])
    print("HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']=%s" % HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'])
    print("HashInstructions['DISK_SIGNATURE']=0x%X" % HashInstructions['DISK_SIGNATURE'])

    #for j in range(len(PhyPartition)):
    #for j in range(1):
    #    print "\n\nPhyPartition[%d] ========================================================= " % (j)
    #    PrintPartitionCollection( PhyPartition[j] )


    print("len(PhyPartition)=",len(PhyPartition))

    if HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']==False:
        ## to be here means we're *not* growing final partition, thereore, obey the sizes they've specified
        for j in range(len(PhyPartition)):
            TempNumPartitions = len(PhyPartition[j])
            if TempNumPartitions>4:
                MinSectorsNeeded = 1 + (TempNumPartitions-3) # need MBR + TempNumPartitions-3 EBRs
            else:
                MinSectorsNeeded = 1    # need MBR only

            for Partition in PhyPartition[j]:
                print("LABEL: '%s' with %d sectors " % (Partition['label'],ConvertKBtoSectors(Partition["size_in_kb"])))

                MinSectorsNeeded += ConvertKBtoSectors(Partition["size_in_kb"])

                #print "LABEL '%s' with size %d sectors" % (Partition['label'],Partition['size_in_kb']/2)


    print("MinSectorsNeeded=%d" % MinSectorsNeeded)
    #sys.exit()  #


    if OutputToCreate == 'gpt':
        PrintBanner("GPT GUID discovered in XML file, Output will be GPT")
    if OutputToCreate == 'mbr':
        PrintBanner("MBR type discovered in XML file, Output will be MBR")


#    PrintPartitionCollection( PhyPartition[0] )
def PrintPartitionCollection(PartitionCollection):

    #print PartitionCollection

    for Partition in PartitionCollection:
        print(Partition)
        print(" ")
        for key in Partition:
            print(key,"\t=>\t",Partition[key])

    #for j in range(NumMBRPartitions):

def ParseCommandLine():
    global XMLFile,OutputToCreate,PhysicalPartitionNumber

    print("\nArgs")
    for i in range(len(sys.argv)):
        print("sys.argv[%d]=%s" % (i,sys.argv[i]))

    print(" ")

    XMLFile = sys.argv[1];

    if len(sys.argv) >= 3:
        m = re.search("mbr|gpt", sys.argv[2] )

        if m is not None:
            OutputToCreate = sys.argv[2]
        else:
            print("Unrecognized option '%s', only 'mbr' or 'gpt' expected" % sys.argv[2])
    else:
        print("\nUser *did* not explicitly specify partition table format (i.e. mbr|gpt)")
        print("\nWill AUTO-DETECT from file")

    if len(sys.argv) >= 4:  # Should mean PHY partition was specified
        m = re.search(r'^\d+$', sys.argv[3] )
        if m is not None:
            PhysicalPartitionNumber = int(sys.argv[3])
            print("PhysicalPartitionNumber specified as %d" % PhysicalPartitionNumber)
        else:
            PrintBigError("ERROR: PhysicalPartitionNumber of disk must only contain numbers, '%s' is not valid" % sys.argv[3])

    print(" ")

# Updates the WriteProtect hash that is used in creating emmc_lock_regions.xml
def UpdateWPhash(Start,Size):
    global hash_w,NumWPregions

    if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']==0:
        return

    #print "\nUpdateWPhash(%i,%i) and currently NumWPregions=%i" % (Start,Size,NumWPregions)
    #print "hash_w[%i]['start_sector']=%i" % (NumWPregions,hash_w[NumWPregions]["start_sector"])
    #print "hash_w[%i]['end_sector']=%i" % (NumWPregions,hash_w[NumWPregions]["end_sector"])
    #print "hash_w[%i]['num_sectors']=%i" % (NumWPregions,hash_w[NumWPregions]["num_sectors"])

    if Start-1 <= hash_w[NumWPregions]["end_sector"]:
        #print "\n\tCurrent Write Protect region already covers the start of this partition (start=%i)" % hash_w[NumWPregions]["start_sector"]

        if (Start + Size - 1) > hash_w[NumWPregions]["end_sector"]:
            print("\n\tCurrent Write Protect region is not big enough at %i sectors, needs to be at least %i sectors" % (hash_w[NumWPregions]["end_sector"]-hash_w[NumWPregions]["start_sector"]+1,Start + Size - 1,))
            while (Start + Size - 1) > hash_w[NumWPregions]["end_sector"]:
                hash_w[NumWPregions]["num_sectors"] += (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES);
                hash_w[NumWPregions]["end_sector"]  += (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES);
                if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
                    hash_w[NumWPregions]["num_boundaries_covered"] = hash_w[NumWPregions]["num_sectors"] / (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)
                else:
                    hash_w[NumWPregions]["num_boundaries_covered"] = 0

            print("\t\tend_sector increased to %i sectors" % hash_w[NumWPregions]["end_sector"])
            print("\t\tnum_sectors increased to %i sectors" % hash_w[NumWPregions]["num_sectors"])

        #print "\n\tCurrent Write Protect region covers this partition (num_sectors=%i)\n" % hash_w[NumWPregions]["num_sectors"]

    else:
        print("\n\tNew write protect region needed")
        #print "\tStart-1\t\t\t\t=%i" % (Start-1)
        #print "\tLAST hash_w[NumWPregions][end_sector]=%i\n" % hash_w[NumWPregions]["end_sector"]


        NumWPregions+=1;

        hash_w.append( {'start_sector':Start,'num_sectors':(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES),'end_sector':Start+(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)-1,'physical_partition_number':0,'boundary_num':0,'num_boundaries_covered':1} )

        hash_w[NumWPregions]["boundary_num"] = Start / (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)

        while (Start + Size - 1) > hash_w[NumWPregions]["end_sector"]:
            #print "\n\tThis region is not big enough though, needs to be %i sectors, but currently only %i" % (Start + Size - 1,hash_w[NumWPregions]["end_sector"])
            hash_w[NumWPregions]["num_sectors"] += (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES);
            hash_w[NumWPregions]["end_sector"]  += (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES);
            #print "\t\tend_sector increased to %i sectors" % hash_w[NumWPregions]["end_sector"]
            #print "\t\tnum_sectors increased to %i sectors" % hash_w[NumWPregions]["num_sectors"]

        hash_w[NumWPregions]["num_boundaries_covered"] = hash_w[NumWPregions]["num_sectors"] / (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']*1024/SECTOR_SIZE_IN_BYTES)

        print("\t\tstart_sector = %i sectors" % hash_w[NumWPregions]["start_sector"])
        print("\t\tend_sector = %i sectors" % hash_w[NumWPregions]["end_sector"])
        print("\t\tnum_sectors = %i sectors\n" % hash_w[NumWPregions]["num_sectors"])

# A8h reflected is 15h, i.e. 10101000 <--> 00010101
def reflect(data,nBits):

    reflection = 0x00000000
    bit = 0

    for bit in range(nBits):
        if(data & 0x01):
            reflection |= (1 << ((nBits - 1) - bit))
        data = (data >> 1);

    return reflection


def CalcCRC32(array,Len):
   k        = 8;            # length of unit (i.e. byte)
   MSB      = 0;
   gx       = 0x04C11DB7;   # IEEE 32bit polynomial
   regs     = 0xFFFFFFFF;   # init to all ones
   regsMask = 0xFFFFFFFF;   # ensure only 32 bit answer

   print("Calculating CRC over byte length of %i" % Len)
   print("%s" % HexPrettyPrint(array,Len))

   for i in range(int(Len)):
      DataByte = array[i]
      DataByte = reflect( DataByte, 8 );

      for j in range(k):
        MSB  = DataByte>>(k-1)  ## get MSB
        MSB &= 1                ## ensure just 1 bit

        regsMSB = (regs>>31) & 1

        regs = regs<<1          ## shift regs for CRC-CCITT

        if regsMSB ^ MSB:       ## MSB is a 1
            regs = regs ^ gx    ## XOR with generator poly

        regs = regs & regsMask; ## Mask off excess upper bits

        DataByte <<= 1          ## get to next bit


   regs          = regs & regsMask ## Mask off excess upper bits
   ReflectedRegs = reflect(regs,32) ^ 0xFFFFFFFF;

   #print "CRC is 0x%.8X\n" % ReflectedRegs

   return ReflectedRegs


def HexPrettyPrint(data,Length):
   szNum = ""
   szAsc = ""
   digest= ""
   P = 16

   ## Called during DLOAD and STREAM
   #log_info("In HexPrettyPrint() len(data)=%d" % len(data))

   ##return  " "## hack

   try:
       if len(data)==0:
           return " "
   except:
       log_debug("Hit Exception in HexPrettyPrint, data is %s" % type(data))
       return " "

   digest = ""

   TempAddress = 0
   szHexDump = "\n\tShowing %d bytes\n\t" % (Length)
   for i in range(int(Length)):
       v = data[i]

       if v == 0x7 and i==0 and Length>5:
           ## Get next 4 bytes
           ##print "Length=",Length
           TempAddress = data[i+4]<<24 | data[i+3]<<16 | data[i+2]<<8 | data[i+1]
           szHexDump += "Suspected Write, Address would be 0x%.8X\n\t" % (TempAddress)

       if i>0 and i % 16==0:
           szHexDump += "%-48s\t%s\n\t" % (szNum,szAsc)
           szNum = ""
           szAsc = ""

       ##print "v=",v," type",type(v)
       ##import pdb; pdb.set_trace()
       #if type(v) is not int:    ## HACK
       #    v = ord(v)  ## convert to unsigned char (integers in python)
       szNum += "%.2X " % v
       if v>=0x20 and v<=0x7E:
           szAsc += "%c"    % v
       else:
           szAsc += "."

   ##import pdb; pdb.set_trace()

   szHexDump += "%-48s\t%s\n%s\n\n" % (szNum,szAsc,digest)

   return szHexDump


def ReturnLow32bits(var):
    return var & 0xFFFFFFFF

def ReturnHigh32bits(var):
    return (var>>32) & 0xFFFFFFFF

def PrintBanner(sz):
    print("\n"+"="*78)
    print(sz)
    print("="*78+"\n")

def ShowUsage():
    PrintBanner("Basic Usage")
    print("python ptool.py -x partition.xml")
    PrintBanner("Advanced Usage")
    print("%-44s\t\tpython ptool.py -x partition.xml" % ("Basic Usage"))
    print("%-44s\t\tpython ptool.py -x partition.xml -s c:\\windows" % ("Search path to find partition.xml"))
    print("%-44s\tpython ptool.py -x partition.xml -p 0" % ("Specify PHY Partition 0, (creates rawprogram0.xml)"))
    print("%-44s\tpython ptool.py -x partition.xml -p 1" % ("Specify PHY Partition 1, (creates rawprogram1.xml)"))
    print("%-44s\tpython ptool.py -x partition.xml -p 2" % ("Specify PHY Partition 2, (creates rawprogram2.xml)"))
    print("%-44s\t\tpython ptool.py -x partition.xml -v" % ("Verbose output"))
    print("%-44s\t\tpython ptool.py -x partition.xml -t c:\\temp" % ("Specify place to put output"))
    print("%-44s\t\tpython ptool.py -x partition.xml -n" % ("Don't require the use of patch file"))

def CreateFinalPartitionBin():
    global OutputFolder

    opfile = open("%spartition.bin" % OutputFolder, "wb")

    for i in range(3):
        FileName = "%spartition%i.bin" % (OutputFolder,i);
        size     = 0

        if os.path.isfile(FileName):
            size = os.path.getsize(FileName)

            ipfile = open(FileName, "rb")
            temp = ipfile.read()
            opfile.write(temp)
            ipfile.close()

        if size < 8192:
            MyArray = [0]*(8192-size)
            for b in MyArray:
                opfile.write(struct.pack("B", b))

    opfile.close()



def prettify(elem):
    """Return a pretty-printed XML string for the Element.
    """
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def UpdatePartitionTable(Bootable,Type,StartSector,Size,Offset,Record):

    #print "Size = %i" % Size

    if Bootable=="true":
        Bootable = 0x80
    else:
        Bootable = 0x00

    Type = ValidateTYPE(Type)

    #print "\tAt Offset=0x%.4X (%d) (%d bytes left)" % (Offset,Offset,len(Record)-Offset)

    Record[Offset]         = Bootable  ; Offset+=1

    Record[Offset:Offset+3]= [0,0,0]   ; Offset+=3

    Record[Offset]         = Type      ; Offset+=1

    Record[Offset:Offset+3]= [0,0,0]   ; Offset+=3

    # First StartSector
    for b in range(4):
        Record[Offset] = ((StartSector>>(b*8)) & 0xFF) ; Offset+=1

    # First StartSector
    for b in range(4):
        Record[Offset] = ((Size>>(b*8)) & 0xFF) ; Offset+=1

    #print "\t\tBoot:0x%.2X, ID:0x%.2X, 0x%.8X, 0x%.8X (%.2fMB)" % (Bootable,Type,StartSector,Size,Size/2048.0)

    return Record

# This function called first, then calls CreateMasterBootRecord and CreateExtendedBootRecords
def CreateMBRPartitionTable(PhysicalPartitionNumber):
    global PhyPartition,opfile,RawProgramXML,HashInstructions,ExtendedPartitionBegins,MBR,PARTITIONBIN, MBRBIN, EBRBIN, PATCHES, RAW_PROGRAM

    k = PhysicalPartitionNumber

    if(k>=len(PhyPartition)):
        print("PHY Partition %i of %i not found" % (k,len(PhyPartition)))
        sys.exit()

    NumPartitions = len(PhyPartition[k])

    print("\n\nOn PHY Partition %d that has %d partitions" % (k,NumPartitions))

    print("\n------------\n")

    print("\nFor PHY Partition %i" % k)
    if(NumPartitions<=4):
        print("\tWe can get away with only an MBR");
        CreateMasterBootRecord(k, NumPartitions )
    else:
        print("\tWe will need an MBR and %d EBRs" % (NumPartitions-3))
        CreateMasterBootRecord(k, 3 )

        ## Now the EXTENDED PARTITION
        print("\nAbout to make EBR, FirstLBA=%i, LastLBA=%i" % (FirstLBA,LastLBA))
        CreateExtendedBootRecords(k,NumPartitions-3)


    PARTITIONBIN    = '%spartition%i.bin'   % (OutputFolder,k)
    MBRBIN          = '%sMBR%i.bin'         % (OutputFolder,k)
    EBRBIN          = '%sEBR%i.bin'         % (OutputFolder,k)
    PATCHES         = '%spatch%i.xml'       % (OutputFolder,k)
    RAW_PROGRAM     = '%srawprogram%i.xml'  % (OutputFolder,k)

    UpdateRawProgram(RawProgramXML,0, 1*SECTOR_SIZE_IN_BYTES/1024.0, k, 0, 1, MBRBIN, 'false', 'MBR')

    if(NumPartitions>4):
        ## There was more than 4 partitions, so EXT partition had to be used
        UpdateRawProgram(RawProgramXML,ExtendedPartitionBegins, (NumPartitions-3)*SECTOR_SIZE_IN_BYTES/1024.0, k, 0, NumPartitions-3, EBRBIN, 'false', 'EXT')          # note file offset is 0

    print("\nptool.py is running from CWD: ", os.getcwd(), "\n")

    opfile = open(PARTITIONBIN, "wb")
    WriteMBR()
    WriteEBR()
    opfile.close()
    print("Created \"%s\"" % PARTITIONBIN)

    opfile = open(MBRBIN, "wb")
    WriteMBR()
    opfile.close()
    print("Created \"%s\"" % MBRBIN)

    opfile = open(EBRBIN, "wb")
    WriteEBR()
    opfile.close()
    print("Created \"%s\"" % EBRBIN)

    opfile = open(RAW_PROGRAM, "w")
    opfile.write( prettify(RawProgramXML) )
    opfile.close()
    print("Created \"%s\"" % RAW_PROGRAM)

    opfile = open(PATCHES, "w")
    opfile.write( prettify(PatchesXML) )
    opfile.close()
    print("Created \"%s\"" % PATCHES)

    for mydict in hash_w:
        #print mydict
        SubElement(EmmcLockRegionsXML, 'program', {'start_sector':"%X" % mydict['start_sector'],'start_sector_dec':str(mydict['start_sector']),
                                       'num_sectors':"%X" % mydict['num_sectors'],'num_sectors_dec':str(mydict['num_sectors']),
                                       'boundary_num':str(mydict['boundary_num']),
                                       'num_boundaries_covered':str(mydict['num_boundaries_covered']),
                                       'physical_partition_number':str(mydict['physical_partition_number']) })


    SubElement(EmmcLockRegionsXML, 'information', {'WRITE_PROTECT_BOUNDARY_IN_KB':str(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']) })

    opfile = open("%semmc_lock_regions.xml" % OutputFolder, "w")

    opfile.write( prettify(EmmcLockRegionsXML) )
    opfile.close()
    print("Created \"%semmc_lock_regions.xml\"" % OutputFolder)

    print("\nUse msp tool to write this information to SD/eMMC card")
    print("\ti.e.")

    if sys.platform.startswith("linux"):
        print("\tsudo python msp.py rawprogram0.xml /dev/sdb    <---- where /dev/sdb is assumed to be your SD/eMMC card")
        print("\tsudo python msp.py patch0.xml /dev/sdb    <---- where /dev/sdb is assumed to be your SD/eMMC card\n\n")
    else:
        print("\tpython msp.py rawprogram0.xml \\\\.\\PHYSICALDRIVE2    <---- where \\\\.\\PHYSICALDRIVE2 is")
        print("\tpython msp.py patch0.xml \\\\.\\PHYSICALDRIVE2    <---- assumed to be your SD/eMMC card\n\n")


  # CreateMasterBootRecord(k,len(PhyPartition[k]) )
def CreateMasterBootRecord(k,NumMBRPartitions):
    global PhyPartition,HashInstructions,MBR,FirstLBA,LastLBA
    print("\nInside CreateMasterBootRecord(%d) -------------------------------------" % NumMBRPartitions)

    MBR             = [0]*SECTOR_SIZE_IN_BYTES
    MBR[440]        = (HashInstructions['DISK_SIGNATURE']>>24)&0xFF
    MBR[441]        = (HashInstructions['DISK_SIGNATURE']>>16)&0xFF
    MBR[442]        = (HashInstructions['DISK_SIGNATURE']>>8)&0xFF
    MBR[443]        = (HashInstructions['DISK_SIGNATURE'])&0xFF

    MBR[510:512]    = [0x55,0xAA]           # magic byte for MBR partitioning - always at this location regardless of SECTOR_SIZE_IN_BYTES

    ## These two values used like so 'num_sectors':str(LastLBA-FirstLBA)
    FirstLBA    = 1    ## the MBR is at 0, Partition 1 is at 1
    LastLBA     = 1

    PartitionSectorSize = 0

    #print "\nOn PHY Partition %d that has %d partitions" % (k,len(PhyPartition[k]))
    for j in range(NumMBRPartitions):   # typically this is 0,1,2

        ## ALL MBR partitions are marked as read-only
        PhyPartition[k][j]['readonly'] = "true"

        PartitionSectorSize = ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb'])    # in sector form, i.e. 1KB = 2 sectors

        print("\n\n%d of %d \"%s\" (readonly=%s) and size=%dKB (%.2fMB or %i sectors)" % (j+1,len(PhyPartition[k]),PhyPartition[k][j]['label'],
                                        PhyPartition[k][j]['readonly'],PhyPartition[k][j]['size_in_kb'],
                                        PhyPartition[k][j]['size_in_kb']/1024.0,ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb'])))


        # Is this sector aligned?
        if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
            AlignedRemainder = FirstLBA % HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'];

            if AlignedRemainder==0:
                print("\tThis partition is ** ALIGNED ** to a %i KB boundary at sector %i (boundary %i)" % (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'],FirstLBA,FirstLBA/(ConvertKBtoSectors(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']))))


        # are we on the very last partition, i.e. did user only specify 3 or less partitions?
        if (j+1) == len(PhyPartition[k]):
            print("\nTHIS IS THE LAST PARTITION")
            print("HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] = %s" % HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'])
            if HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']==True:
                SectorOffsetPatchBefore = 0
                SectorOffsetPatchAfter  = 0
                ByteOffset              = 0x1CA+j*16
                UpdatePatch(str(SectorOffsetPatchBefore),str(ByteOffset),k,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA),"partition%d.bin" % k, "Update last partition with actual size.")
                UpdatePatch(str(SectorOffsetPatchBefore),str(ByteOffset),k,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA),"MBR%d.bin" % k, "Update last partition with actual size.")
                UpdatePatch(str(SectorOffsetPatchAfter), str(ByteOffset),k,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA),"DISK", "Update 'Update last partition with actual size.")

        # Update the Write-Protect hash
        if PhyPartition[k][j]['readonly']=="true":
            UpdateWPhash(FirstLBA, PartitionSectorSize)

        LastLBA += PartitionSectorSize ## increase by num sectors, LastLBA inclusive, so add 1 for size

        ## Default for each partition is no file
        FileToProgram           = [""]
        FileOffset              = [0]
        FilePartitionOffset     = [0]
        FileAppsbin             = ["false"]
        FileSparse              = ["false"]

        if 'filename' in PhyPartition[k][j]:
            ##print "filename exists"
            #print PhyPartition[k][j]['filename']
            #print FileToProgram[0]


            FileToProgram[0]            = PhyPartition[k][j]['filename'][0]
            FileOffset[0]               = PhyPartition[k][j]['fileoffset'][0]
            FilePartitionOffset[0]      = PhyPartition[k][j]['filepartitionoffset'][0]
            FileAppsbin[0]              = PhyPartition[k][j]['appsbin'][0]
            FileSparse[0]               = PhyPartition[k][j]['sparse'][0]

            for z in range(1,len(PhyPartition[k][j]['filename'])):
                FileToProgram.append( PhyPartition[k][j]['filename'][z] )
                FileOffset.append( PhyPartition[k][j]['fileoffset'][z] )
                FilePartitionOffset.append( PhyPartition[k][j]['filepartitionoffset'][z] )
                FileAppsbin.append( PhyPartition[k][j]['appsbin'][z] )
                FileSparse.append( PhyPartition[k][j]['sparse'][z] )

            #print PhyPartition[k][j]['fileoffset']


        #for z in range(len(FileToProgram)):
        #    print "FileToProgram[",z,"]=",FileToProgram[z]
        #    print "FileOffset[",z,"]=",FileOffset[z]
        #    print " "

        PartitionLabel  = ""
        Type            = ""
        Bootable        = "false"

        ## Now update with the real values
        if 'label' in PhyPartition[k][j]:
            PartitionLabel = PhyPartition[k][j]['label']
        if 'type' in PhyPartition[k][j]:
            Type = PhyPartition[k][j]['type']
        if 'bootable' in PhyPartition[k][j]:
            Bootable = PhyPartition[k][j]['bootable']

        ## Now it is time to update the partition table
        offset = 0x1BE + (j*16)

        MBR = UpdatePartitionTable(Bootable,Type,FirstLBA,PartitionSectorSize,offset,MBR)


        for z in range(len(FileToProgram)):
            #print "File: ",FileToProgram[z]
            #print "FilePartitionOffset[z]=",FilePartitionOffset[z]
            UpdateRawProgram(RawProgramXML, FirstLBA+FilePartitionOffset[z], PartitionSectorSize*SECTOR_SIZE_IN_BYTES/1024.0, k, FileOffset[z], PartitionSectorSize-FilePartitionOffset[z], FileToProgram[z], FileSparse[z], PartitionLabel)

        FirstLBA = LastLBA      # getting ready for next partition, FirstLBA is now where we left off

# CreateExtendedBootRecords(k,len(PhyPartition[k])-3)
def CreateExtendedBootRecords(k,NumEBRPartitions):
    global PhyPartition,HashInstructions,MBR,EBR,FirstLBA,LastLBA,ExtendedPartitionBegins
    print("\nInside CreateExtendedBootRecords(%d) -----------------------------------------" % NumEBRPartitions)

    ## Step 1 is to update the MBR with the size of the EXT partition
    ## in which logical partitions will be created

    EBROffset = 0

    print("EBROffset=",EBROffset)

    ExtendedPartitionBegins = FirstLBA

    if HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']==True:
        print("Extended Partition begins at FirstLBA=%i\n" % (ExtendedPartitionBegins))
        MBR=UpdatePartitionTable("false","05",FirstLBA,0x0,0x1EE,MBR)  ## offset at 0x1EE is the last entry in MBR
    else:
        print("Extended Partition begins at FirstLBA=%i, size is %i\n" % (ExtendedPartitionBegins,MinSectorsNeeded-FirstLBA))
        MBR=UpdatePartitionTable("false","05",FirstLBA,MinSectorsNeeded-FirstLBA,0x1EE,MBR)  ## offset at 0x1EE is the last entry in MBR

    ## Still patch no matter what, since this can still go on any size card
    UpdatePatch('0',str(0x1FA),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(ExtendedPartitionBegins),"partition%d.bin" % k, "Update MBR with the length of the EXT Partition.")
    UpdatePatch('0',str(0x1FA),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(ExtendedPartitionBegins),"MBR%d.bin" % k, "Update MBR with the length of the EXT Partition.")
    UpdatePatch('0',str(0x1FA),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(ExtendedPartitionBegins),"DISK", "Update MBR with the length of the EXT Partition.")

    UpdateWPhash(FirstLBA, NumEBRPartitions)

    ## Need to make room for the EBR tables
    FirstLBA        += NumEBRPartitions
    LastLBA         += NumEBRPartitions

    print("FirstLBA now equals %d since NumEBRPartitions=%d" % (FirstLBA,NumEBRPartitions))

    offset                  = 0     # offset to EBR array which gets EBR.extend( [0]*SECTOR_SIZE_IN_BYTES ) for each EBR
    SectorsTillNextBoundary = 0     # reset


    # EBROffset is the num sectors from the location of the EBR to the actual logical partition
    # and because we group all the EBRs together,
    #   EBR0 is NumEBRPartitions away from EXT0
    #   EBR1 is NumEBRPartitions-1+SizeOfEXT0 away from EXT1 and so on
    #   EBR2 is NumEBRPartitions-2+SizeOfEXT0+SizeOfEXT1 away from EXT2 and so on
    # Thus EBROffset is constantly growing

    # Also since the EBRs must be write protected, we must ensure that it ends
    # on a WP boundary, i.e. HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']

    ## NOTE: We only have extended partitions when there are more than 4 partitions
    ## meaning 3 primary and then 2 extended. Thus everything here is offset from 3
    ## since the first 3 primary partitions were 0,1,2
    EBR = []
    for j in range(3,(NumEBRPartitions+3)):
        SectorsTillNextBoundary = 0
        EBR.extend( [0]*SECTOR_SIZE_IN_BYTES )

        #print "hash_w[%i]['start_sector']=%i" % (NumWPregions,hash_w[NumWPregions]["start_sector"])
        #print "hash_w[%i]['end_sector']=%i" % (NumWPregions,hash_w[NumWPregions]["end_sector"])
        #print "hash_w[%i]['num_sectors']=%i" % (NumWPregions,hash_w[NumWPregions]["num_sectors"])

        PartitionSectorSize = ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb'])

        ##print "\nPartition name='%s' (readonly=%s)" % (PhyPartition[k][j]['label'], PhyPartition[k][j]['readonly'])
        print("\n\n%d of %d \"%s\" (readonly=%s) and size=%dKB (%.2fMB or %i sectors)" %(j+1,len(PhyPartition[k]),PhyPartition[k][j]['label'],PhyPartition[k][j]['readonly'],PhyPartition[k][j]['size_in_kb'],PhyPartition[k][j]['size_in_kb']/1024.0,ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb'])))
        print("\tFirstLBA=%d (with size %d sectors) and LastLBA=%d" % (FirstLBA,ConvertKBtoSectors(PhyPartition[k][j]['size_in_kb']),LastLBA))

        if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
            SectorsTillNextBoundary = ReturnNumSectorsTillBoundary(FirstLBA,HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'])

        # Only the last partition can be re-sized. Are we on the very last partition?
        if (j+1) == len(PhyPartition[k]):
            print("\n\tTHIS IS THE LAST PARTITION")

            if PhyPartition[k][j]['readonly']=="true":
                PhyPartition[k][j]['readonly']="false"
                print("\tIt cannot be marked as read-only, it is now set to writeable")

            if HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK']==True:
                ## Here I'd want a patch for this
                print("\tHashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'] = %s" % HashInstructions['GROW_LAST_PARTITION_TO_FILL_DISK'])

                print("\njust set LAST PartitionSectorSize = 0 (it was %d)" % PartitionSectorSize)
                PartitionSectorSize = 0
                print("This means the partition table will have a zero in it")
                LastPartitionBeginsAt = FirstLBA

            NumEBRs = (len(PhyPartition[k])-3)
            SectorOffsetPatchBefore = NumEBRs
            SectorOffsetPatchAfter  = ExtendedPartitionBegins+NumEBRs-1
            ByteOffset              = 0x1CA

            ## Patch no matter what
            UpdatePatch(str(SectorOffsetPatchBefore),str(ByteOffset),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA+1),"partition%d.bin" % k, "Update last partition with actual size.")
            UpdatePatch(str(SectorOffsetPatchBefore-1),str(ByteOffset),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA+1),"EBR%d.bin" % k, "Update last partition with actual size.")
            UpdatePatch(str(SectorOffsetPatchAfter), str(ByteOffset),PhysicalPartitionNumber,4,"NUM_DISK_SECTORS-%s." % str(FirstLBA+1),"DISK", "Update last partition with actual size.")


        print("\tPhyPartition[k][j]['align']=",PhyPartition[k][j]['align'])
        print("\tSectorsTillNextBoundary=",SectorsTillNextBoundary)

        if PhyPartition[k][j]['readonly']=="true":
            ## to be here means this partition is read-only, so see if we need to move the start
            if FirstLBA <= hash_w[NumWPregions]["end_sector"]:
                print("Great, We *don't* need to move FirstLBA (%d) since it's covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"]))
                pass
            else:
                print("\tFirstLBA (%d) is *not* covered by the end of the WP region (%d),\n\tit needs to be moved to be aligned to %d" % (FirstLBA,hash_w[NumWPregions]["end_sector"],FirstLBA + SectorsTillNextBoundary))
                FirstLBA += SectorsTillNextBoundary
        elif PhyPartition[k][j]['align']=="true":
            ## to be here means this partition *must* be on an ALIGN boundary
            SectorsTillNextBoundary = ReturnNumSectorsTillBoundary(FirstLBA,HashInstructions['ALIGN_BOUNDARY_IN_KB'])
            if SectorsTillNextBoundary>0:
                print("\tSectorsTillNextBoundary=%d, FirstLBA=%d it needs to be moved to be aligned to %d" % (SectorsTillNextBoundary,FirstLBA,FirstLBA + SectorsTillNextBoundary))
                print("\tHashInstructions['ALIGN_BOUNDARY_IN_KB']=",HashInstructions['ALIGN_BOUNDARY_IN_KB'])
                FirstLBA += SectorsTillNextBoundary

                AlignedRemainder = FirstLBA % HashInstructions['ALIGN_BOUNDARY_IN_KB'];

                if AlignedRemainder==0:
                    print("\tThis partition is ** ALIGNED ** to a %i KB boundary at sector %i (boundary %i)" % (HashInstructions['ALIGN_BOUNDARY_IN_KB'],FirstLBA,FirstLBA/(ConvertKBtoSectors(HashInstructions['ALIGN_BOUNDARY_IN_KB']))))

        else:
            print("\n\tThis partition is *NOT* readonly (or does not have align='true')")
            ## to be here means this partition is writeable, so see if we need to move the start
            if FirstLBA <= hash_w[NumWPregions]["end_sector"]:
                print("\tWe *need* to move FirstLBA (%d) since it's covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"]))
                print("\nhash_w[NumWPregions]['end_sector']=%i" % hash_w[NumWPregions]["end_sector"]);
                print("FirstLBA=%i\n" %FirstLBA);
                FirstLBA += SectorsTillNextBoundary

                print("\tFirstLBA is now %d" % (FirstLBA))
            else:
                #print "Great, We *don't* need to move FirstLBA (%d) since it's *not* covered by the end of the current WP region (%d)" % (FirstLBA,hash_w[NumWPregions]["end_sector"])
                pass

        if HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']>0:
            AlignedRemainder = FirstLBA % HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'];

            if AlignedRemainder==0:
                print("\tThis partition is ** ALIGNED ** to a %i KB boundary at sector %i (boundary %i)" % (HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'],FirstLBA,FirstLBA/(ConvertKBtoSectors(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']))))

        if PhyPartition[k][j]['readonly']=="true":
            UpdateWPhash(FirstLBA, PartitionSectorSize)

        LastLBA = FirstLBA + PartitionSectorSize

        print("\n\tFirstLBA=%u, LastLBA=%u, PartitionSectorSize=%u" % (FirstLBA,LastLBA,PartitionSectorSize))

        print("\tLastLBA is currently %i sectors" % LastLBA)
        print("\tCard size of at least %.1fMB needed (%u sectors)" % (LastLBA/2048.0,LastLBA))
        PhyPartition[k][j]['size_in_kb'] = PartitionSectorSize/2

        ## Default for each partition is no file
        FileToProgram           = [""]
        FileOffset              = [0]
        FilePartitionOffset     = [0]
        FileAppsbin             = ["false"]
        FileSparse              = ["false"]

        if 'filename' in PhyPartition[k][j]:
            ##print "filename exists"
            #print PhyPartition[k][j]['filename']
            #print FileToProgram[0]

            FileToProgram[0]            = PhyPartition[k][j]['filename'][0]
            FileOffset[0]               = PhyPartition[k][j]['fileoffset'][0]
            FilePartitionOffset[0]      = PhyPartition[k][j]['filepartitionoffset'][0]
            FileAppsbin[0]              = PhyPartition[k][j]['appsbin'][0]
            FileSparse[0]               = PhyPartition[k][j]['sparse'][0]

            for z in range(1,len(PhyPartition[k][j]['filename'])):
                FileToProgram.append( PhyPartition[k][j]['filename'][z] )
                FileOffset.append( PhyPartition[k][j]['fileoffset'][z] )
                FilePartitionOffset.append( PhyPartition[k][j]['filepartitionoffset'][z] )
                FileAppsbin.append( PhyPartition[k][j]['appsbin'][z] )
                FileSparse.append( PhyPartition[k][j]['sparse'][z] )

            #print PhyPartition[k][j]['fileoffset']


        #for z in range(len(FileToProgram)):
        #    print "FileToProgram[",z,"]=",FileToProgram[z]
        #    print "FileOffset[",z,"]=",FileOffset[z]
        #    print " "

        PartitionLabel  = ""
        Type            = ""
        Bootable        = "false"


        if 'label' in PhyPartition[k][j]:
            PartitionLabel = PhyPartition[k][j]['label']
        if 'type' in PhyPartition[k][j]:
            Type = PhyPartition[k][j]['type']
        if 'bootable' in PhyPartition[k][j]:
            Bootable = PhyPartition[k][j]['bootable']


        ## Update main logical partition
        offset += 0x1BE     ## this naturally increments to 0x200, then 0x400 etc

        ##UpdatePartitionTable(Bootable,Type,EBROffset,PartitionSectorSize,offset) ; offset +=16
        EBR = UpdatePartitionTable(Bootable,Type,FirstLBA-ExtendedPartitionBegins-EBROffset,PartitionSectorSize,offset,EBR) ; offset +=16

        ## Update EXT, i.e. are there more partitions to come?
        if (j+1) == (NumEBRPartitions+3):
            ## No, this is the very last so indicate no more logical partitions
            EBR = UpdatePartitionTable("false","00",0,0,offset,EBR)    ; offset +=16  ## on last partition, so no more
        else:
            ## Yes, at least one more, so indicate EXT type of 05
            EBR = UpdatePartitionTable("false","05",j-2,1,offset,EBR)  ; offset +=16

        ## Update last 2 which are always blank
        EBR = UpdatePartitionTable("false","00",0,0,offset,EBR)        ; offset +=16
        EBR = UpdatePartitionTable("false","00",0,0,offset,EBR)        ; offset +=16

        EBR[offset]     = 0x55      ; offset +=1
        EBR[offset]     = 0xAA      ; offset +=1


        ## Now update EBROffset
        EBROffset += 1                      # Each EBR gets us one closer

        for z in range(len(FileToProgram)):
            #print "File: ",FileToProgram[z]
            #print "FilePartitionOffset[z]=",FilePartitionOffset[z]
            UpdateRawProgram(RawProgramXML,FirstLBA+FilePartitionOffset[z], PartitionSectorSize*SECTOR_SIZE_IN_BYTES/1024.0, k, FileOffset[z], PartitionSectorSize-FilePartitionOffset[z], FileToProgram[z], FileSparse[z], PartitionLabel)

        FirstLBA = LastLBA      # getting ready for next partition, FirstLBA is now where we left off


    print("\n------------------------------------------------------------------------------")
    print("             LastLBA is currently %i sectors" % (LastLBA))
    print("       Card size of at least %.1fMB needed (%u sectors)" % (LastLBA/2048.0,LastLBA))
    print("------------------------------------------------------------------------------")

def ReturnNumSectorsTillBoundary(CurrentLBA, BoundaryInKB):
    #Say BoundaryInKB is 65536 (64MB)
    #    if SECTOR_SIZE_IN_BYTES=512,  BoundaryLBA=131072
    #    if SECTOR_SIZE_IN_BYTES=4096, BoundaryLBA=16384

    #Say were at the 63MB boundary, then
    #    if SECTOR_SIZE_IN_BYTES=512,  CurrentLBA=129024
    #    if SECTOR_SIZE_IN_BYTES=4096, CurrentLBA=16128

    # Distance is then 1MB
    #    if SECTOR_SIZE_IN_BYTES=512,  DistanceLBA=2048   (2048*512=1MB)
    #    if SECTOR_SIZE_IN_BYTES=4096, DistanceLBA=256    (256*4096=1MB)

    ##import pdb; pdb.set_trace()

    x = 0
    if BoundaryInKB>0:
        if (CurrentLBA%ConvertKBtoSectors(BoundaryInKB)) > 0:
            x = ConvertKBtoSectors(BoundaryInKB) - (CurrentLBA%ConvertKBtoSectors(BoundaryInKB))

    ##print "\tFYI: Increase by %dKB (%d sectors) if you want to align to %i KB boundary at sector %d" % (x/2,x,BoundaryInKB,CurrentLBA+x)
    return x


def WriteMBR():
    global opfile,MBR
    for b in MBR:
        opfile.write(struct.pack("B", b))

def WriteEBR():
    global opfile,EBR
    for b in EBR:
        opfile.write(struct.pack("B", b))

def PrintBigError(sz):
    print("\t _________________ ___________ ")
    print("\t|  ___| ___ \\ ___ \\  _  | ___ \\")
    print("\t| |__ | |_/ / |_/ / | | | |_/ /")
    print("\t|  __||    /|    /| | | |    / ")
    print("\t| |___| |\\ \\| |\\ \\\\ \\_/ / |\\ \\ ")
    print("\t\\____/\\_| \\_\\_| \\_|\\___/\\_| \\_|\n")

    if len(sz)>0:
        print(sz)
        sys.exit(1)


def find_file(filename, search_paths):
    print("\n\n\tLooking for ",filename)
    print("\t"+"-"*40)
    for x in search_paths:
        print("\tSearching ",x)
        temp = os.path.join(x, filename)
        if os.path.exists(temp):
            print("\n\t**Found %s (%i bytes)" % (temp,os.path.getsize(temp)))
            return temp

    ## search cwd last
    print("\tSearching ",os.getcwd())
    if os.path.exists(filename):
        print("\n\t**Found %s (%i bytes)" % (filename,os.path.getsize(filename)))
        return filename

    print("\tCound't find file\n")
    return None

## ==============================================================================================
## ==============================================================================================
## ==============================================================================================
## =====main()===================================================================================
## ==============================================================================================
## ==============================================================================================
## ==============================================================================================

if len(sys.argv) < 2:
    CreateErasingRawProgramFiles()
    ShowUsage()
    sys.exit(); # error

print("\nCWD: ", os.getcwd(), "\n")

try:
    opts, args = getopt.getopt(sys.argv[1:], "x:f:p:s:t:g:k:v:en", ["xml=", "format=", "partition=", "search_path=", "location=", "sequentialguid=", "use128partitions=", "verbose=","erasefirst","nopatch"])
except getopt.GetoptError as err:
    # print help information and exit:
    print(str(err)) # will print something like "option -a not recognized"
    ShowUsage()
    sys.exit(1)

XMLFile= "adalovelace"
OutputToCreate          = None ## sys.argv[2]
PhysicalPartitionNumber = 0     ## sys.argv[3]
search_paths            = []

verbose                 = False
UsingGetOpts            = False
sequentialguid          = 0
force128partitions      = 0
PhysicalPartitionNumber = -1
erasefirst              = 0

for o, a in opts:
    if o in ("-x", "--xml"):
        UsingGetOpts = True
        XMLFile = a
    elif o in ("-t", "--location"):
        OutputFolder = a
        OutputFolder = re.sub(r"\\$","",OutputFolder)    # remove final slash if it exists
        OutputFolder = re.sub(r"/$","",OutputFolder)     # remove final slash if it exists

        OutputFolder += "/"     # slashes will all be corrected below

        if sys.platform.startswith("linux"):
            OutputFolder = re.sub(r"\\","/",OutputFolder)   # correct slashes
        else:
            OutputFolder = re.sub(r"/","\\\\",OutputFolder) # correct slashes

        print("OutputFolder=",OutputFolder)
        EnsureDirectoryExists(OutputFolder) # only need to call once

    elif o in ("-f", "--format"):
        UsingGetOpts = True
        OutputToCreate = a
        m = re.search("^(mbr|gpt)$", a)     #mbr|gpt
        if m is None:
            PrintBigError("ERROR: Only MBR or GPT is supported")
        else:
            OutputToCreate = m.group(1)

    elif o in ("-s", "--search_path"):
        ## also allow seperating commas
        for x in a.strip("\n").split(","):
            search_paths.append(x)

    elif o in ("-k", "--use128partitions"):
        ## Force there to be 128 partitions in the partition table
        m = re.search(r'\d', a)     #mbr|gpt
        if m is None:
            force128partitions = 0
        else:
            force128partitions = 1

    elif o in ("-e", "--erasefirst"):
        erasefirst = 1;

    elif o in ("-n", "--nopatch"):
        gen_patch = False;

    elif o in ("-g", "--sequentialguid"):
        ## also allow seperating commas
        m = re.search(r'\d', a)     #mbr|gpt
        if m is None:
            sequentialguid = 0
        else:
            sequentialguid = 1

    elif o in ("-p", "--partition"):
        UsingGetOpts = True
        PhysicalPartitionNumber = a
        m = re.search(r'^(\d)$', a)     #0|1|2
        if m is None:
            PrintBigError("ERROR: PhysicalPartitionNumber (-p) must be a number, you supplied *",a,"*")
        else:
            PhysicalPartitionNumber = int(m.group(1))
    elif o in ("-v", "--verbose"):
        UsingGetOpts = True
        verbose = True
    else:
        print("o=",o)
        assert False, "unhandled option"

if UsingGetOpts is False:
    #ParseCommandLine()
    PrintBanner("NEW USAGE - Note this program will auto-detect if it's GPT or MBR")
    ShowUsage()
    sys.exit(1)

print("XMLFile=",XMLFile)
if len(OutputFolder)>0:
    print("OutputFolder=",OutputFolder)
print("OutputToCreate",OutputToCreate)
print("PhysicalPartitionNumber",PhysicalPartitionNumber)
print("verbose",verbose)


XMLFile = find_file(XMLFile, search_paths)
if XMLFile is None:
    PrintBigError("ERROR: Could not find file")

ParseXML(XMLFile)  # parses XMLFile, discovers if GPT or MBR

PrintBanner("OutputToCreate ===> '%s'" % OutputToCreate)

def InitializeXMLFileVars():
    global EmmcLockRegionsXML,RawProgramXML,RawProgramXML_Wipe,PatchesXML,RawProgramXML_Blank,PatchesXML_Blank

    EmmcLockRegionsXML = Element('protect')
    EmmcLockRegionsXML.append(Comment("NOTE: This is an ** Autogenerated file **"))
    EmmcLockRegionsXML.append(Comment('NOTE: Sector size is %ibytes, WRITE_PROTECT_BOUNDARY_IN_KB=%i, WRITE_PROTECT_BOUNDARY_IN_SECTORS=%i' % (SECTOR_SIZE_IN_BYTES,HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB'],ConvertKBtoSectors(HashInstructions['WRITE_PROTECT_BOUNDARY_IN_KB']))))
    EmmcLockRegionsXML.append(Comment("NOTE: \"num_sectors\" in HEX \"start_sector\" in HEX, i.e. 10 really equals 16 !!"))

    RawProgramXML = Element('data')
    RawProgramXML.append(Comment('NOTE: This is an ** Autogenerated file **'))
    RawProgramXML.append(Comment('NOTE: Sector size is %ibytes'%SECTOR_SIZE_IN_BYTES))

    RawProgramXML_Wipe = Element('data')
    RawProgramXML_Wipe.append(Comment('NOTE: This is an ** Autogenerated file **'))
    RawProgramXML_Wipe.append(Comment('NOTE: Sector size is %ibytes'%SECTOR_SIZE_IN_BYTES))

    PatchesXML = Element('patches')
    PatchesXML.append(Comment('NOTE: This is an ** Autogenerated file **'))
    PatchesXML.append(Comment('NOTE: Patching is in little endian format, i.e. 0xAABBCCDD will look like DD CC BB AA in the file or on disk'))
    PatchesXML.append(Comment('NOTE: This file is used by Trace32 - So make sure to add decimals, i.e. 0x10-10=0, *but* 0x10-10.=6.'))

    RawProgramXML_Blank = Element('data')
    RawProgramXML_Blank.append(Comment('NOTE: This is an ** Autogenerated file **'))
    RawProgramXML_Blank.append(Comment('NOTE: This file writes a VALID but EMPTY partition table to sector 0 **'))
    RawProgramXML_Blank.append(Comment('NOTE: Sector size is %ibytes'%SECTOR_SIZE_IN_BYTES))

    PatchesXML_Blank = Element('patches')
    PatchesXML_Blank.append(Comment('NOTE: This is an ** Autogenerated file **'))
    PatchesXML_Blank.append(Comment('NOTE: Patching is in little endian format, i.e. 0xAABBCCDD will look like DD CC BB AA in the file or on disk'))
    PatchesXML_Blank.append(Comment('NOTE: This file is used by Trace32 - So make sure to add decimals, i.e. 0x10-10=0, *but* 0x10-10.=6.'))

if OutputToCreate == "gpt":
    if PhysicalPartitionNumber == -1:
        for PhysicalPartitionNumber in range(0,len(PhyPartition)):  ## where len(PhyPartition) is typically a maximum of 8
            InitializeXMLFileVars()
            CreateGPTPartitionTable( PhysicalPartitionNumber ) ## wants it in LBA format, i.e. 1KB = 2 sectors of size SECTOR_SIZE_IN_BYTES
        CreateErasingRawProgramFiles()
        print("\n\nNOTE: All Physical Partitions / LUNs were created since user did not use -p 0 option\n\n")
    else:
        InitializeXMLFileVars()
        CreateGPTPartitionTable( PhysicalPartitionNumber, True ) ## wants it in LBA format, i.e. 1KB = 2 sectors of size SECTOR_SIZE_IN_BYTES
        CreateErasingRawProgramFiles()
else:
    InitializeXMLFileVars()
    CreateMBRPartitionTable( PhysicalPartitionNumber )
    CreateFinalPartitionBin()

