#include <cstring>
#include <memory>
#include <rs_driver/msg/point_cloud_msg.hpp>
#include <rs_driver/driver/decoder/decoder_RS128.hpp>

using namespace robosense::lidar;
using Cloud=PointCloudT<PointXYZIRT>;
static RSDecoderParam configuration() {
  RSDecoderParam settings;
  settings.wait_for_difop=true; settings.config_from_file=false;
  settings.use_lidar_clock=true; settings.dense_points=false;
  settings.min_distance=0.4f; settings.max_distance=250.0f;
  return settings;
}
class Ruby : public DecoderRS128<Cloud> {
 public:
  unsigned int errors=0,split_notifications=0;
  Ruby(): DecoderRS128<Cloud>(configuration()) {
    point_cloud_=std::make_shared<Cloud>();
    regCallback([this](const Error&){++errors;},[this](uint16_t,double){++split_notifications;});
  }
  bool ready()const {return angles_ready_;}
};
extern "C" {
void* ruby_create(){try{return new Ruby();}catch(...){return nullptr;}}
void ruby_destroy(void* state){delete static_cast<Ruby*>(state);}
int ruby_difop(void* state,const uint8_t* bytes,unsigned int count) {
  if(!state || count!=sizeof(RS128DifopPkt))return -1;
  auto decoder=static_cast<Ruby*>(state);
  decoder->processDifopPkt(bytes,count);
  return decoder->ready() && decoder->errors==0 ? 0 : -2;
}
int ruby_packet(void* state,const uint8_t* bytes,unsigned int count,void* output,unsigned int capacity) {
  if(!state || count!=sizeof(RS128MsopPkt) || capacity<384*sizeof(PointXYZIRT))return -1;
  static_assert(sizeof(PointXYZIRT)==23,"driver point layout changed");
  auto decoder=static_cast<Ruby*>(state);
  auto packet=reinterpret_cast<const RS128MsopPkt*>(bytes);
  if(!decoder->ready() || packet->header.lidar_type!=4)return -2;
  for(const auto& block:packet->blocks)if(block.id[0]!=0xfe)return -3;
  decoder->point_cloud_->points.clear();
  decoder->processMsopPkt(bytes,count);
  if(decoder->errors || decoder->point_cloud_->points.size()!=384)return -4;
  std::memcpy(output,decoder->point_cloud_->points.data(),384*sizeof(PointXYZIRT));
  return 0;
}
unsigned int ruby_split_notifications(void* state){return static_cast<Ruby*>(state)->split_notifications;}
unsigned int ruby_vertical_offset(){return offsetof(RS128DifopPkt,vert_angle_cali);}
unsigned int ruby_horizontal_offset(){return offsetof(RS128DifopPkt,horiz_angle_cali);}
unsigned int ruby_mode_offset(){return offsetof(RS128DifopPkt,return_mode);}
unsigned int ruby_family_offset(){return offsetof(RSMsopHeaderV2,lidar_type);}
}
