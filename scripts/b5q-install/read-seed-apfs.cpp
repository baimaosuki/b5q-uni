// Read-only inspection of a regular scratch APFS image through apfs-fuse's
// library. Reports original on-disk owners/modes; no uid override or mounting.
#include <ApfsLib/ApfsContainer.h>
#include <ApfsLib/ApfsVolume.h>
#include <ApfsLib/ApfsDir.h>
#include <ApfsLib/Device.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <memory>
#include <sys/stat.h>
int main(int argc,char **argv){
 if(argc<4||!std::filesystem::is_regular_file(argv[1]))return 2;
 std::unique_ptr<Device> dev(Device::OpenDevice(argv[1]));if(!dev)return 3;
 ApfsContainer container(dev.get(),0,dev->GetSize());if(!container.Init())return 4;
 std::unique_ptr<ApfsVolume> vol(container.GetVolume(0));if(!vol)return 5;
 ApfsDir dir(*vol);
 for(int i=3;i<argc;++i){
  std::string path=argv[i],part;std::istringstream pieces(path);uint64_t inode=2;
  while(std::getline(pieces,part,'/')){
   if(part.empty()||part=="."||part=="..")return 6;
   ApfsDir::DirRec rec;if(!dir.LookupName(rec,inode,part.c_str())){std::cerr<<"missing: "<<path<<"\n";return 7;}inode=rec.file_id;
  }
  ApfsDir::Inode info;if(!dir.GetInode(info,inode))return 8;
  std::cout<<path<<'\t'<<info.owner<<'\t'<<info.group<<'\t'<<std::oct<<info.mode<<std::dec<<'\t'<<info.ds_size<<'\n';
  if(S_ISDIR(info.mode))continue;
  if(!S_ISREG(info.mode)||info.ds_size>4*1024*1024)return 9;
  std::vector<uint8_t> bytes(info.ds_size);
  if(!bytes.empty()&&!dir.ReadFile(bytes.data(),info.private_id,0,bytes.size()))return 10;
  auto target=std::filesystem::path(argv[2])/path;std::filesystem::create_directories(target.parent_path());
  std::ofstream out(target,std::ios::binary);out.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());if(!out)return 11;
 }
}
