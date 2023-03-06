// Generated by gencpp from file active_grasp/Reset.msg
// DO NOT EDIT!


#ifndef ACTIVE_GRASP_MESSAGE_RESET_H
#define ACTIVE_GRASP_MESSAGE_RESET_H

#include <ros/service_traits.h>


#include <active_grasp/ResetRequest.h>
#include <active_grasp/ResetResponse.h>


namespace active_grasp
{

struct Reset
{

typedef ResetRequest Request;
typedef ResetResponse Response;
Request request;
Response response;

typedef Request RequestType;
typedef Response ResponseType;

}; // struct Reset
} // namespace active_grasp


namespace ros
{
namespace service_traits
{


template<>
struct MD5Sum< ::active_grasp::Reset > {
  static const char* value()
  {
    return "4dd9de15958dc8059c48f7ba8054e4b8";
  }

  static const char* value(const ::active_grasp::Reset&) { return value(); }
};

template<>
struct DataType< ::active_grasp::Reset > {
  static const char* value()
  {
    return "active_grasp/Reset";
  }

  static const char* value(const ::active_grasp::Reset&) { return value(); }
};


// service_traits::MD5Sum< ::active_grasp::ResetRequest> should match
// service_traits::MD5Sum< ::active_grasp::Reset >
template<>
struct MD5Sum< ::active_grasp::ResetRequest>
{
  static const char* value()
  {
    return MD5Sum< ::active_grasp::Reset >::value();
  }
  static const char* value(const ::active_grasp::ResetRequest&)
  {
    return value();
  }
};

// service_traits::DataType< ::active_grasp::ResetRequest> should match
// service_traits::DataType< ::active_grasp::Reset >
template<>
struct DataType< ::active_grasp::ResetRequest>
{
  static const char* value()
  {
    return DataType< ::active_grasp::Reset >::value();
  }
  static const char* value(const ::active_grasp::ResetRequest&)
  {
    return value();
  }
};

// service_traits::MD5Sum< ::active_grasp::ResetResponse> should match
// service_traits::MD5Sum< ::active_grasp::Reset >
template<>
struct MD5Sum< ::active_grasp::ResetResponse>
{
  static const char* value()
  {
    return MD5Sum< ::active_grasp::Reset >::value();
  }
  static const char* value(const ::active_grasp::ResetResponse&)
  {
    return value();
  }
};

// service_traits::DataType< ::active_grasp::ResetResponse> should match
// service_traits::DataType< ::active_grasp::Reset >
template<>
struct DataType< ::active_grasp::ResetResponse>
{
  static const char* value()
  {
    return DataType< ::active_grasp::Reset >::value();
  }
  static const char* value(const ::active_grasp::ResetResponse&)
  {
    return value();
  }
};

} // namespace service_traits
} // namespace ros

#endif // ACTIVE_GRASP_MESSAGE_RESET_H
