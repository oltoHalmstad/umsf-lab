#include <cmath>
#include <fstream>
#include <string>
#include <filesystem>
#include "umsf_features.h"
#include "umsf_buffer.h"
#include "umsf_gwcore.h"
using namespace umsf;
int main(int argc,char**argv) {
    if(argc!=2) return 2;
    std::filesystem::create_directories(argv[1]);
    std::string dir=std::string(argv[1])+"/";
    RuleConfig cfg;
    std::ofstream p(dir+"physio.csv");
    p<<"completeness,valid_fraction,motion_mg,quality,artifact_flags,channel_flags,hr,spo2,ppg_samples,motion_rms\n";
    for(int n=0;n<=1000;n+=50) for(int v=0;v<=10;++v) for(int motion: {0,100,150,200,400}) {
        PhysioWindow w(cfg);
        for(int i=0;i<n;++i) w.add_ppg(80000,i<n*v/10?100000:10000);
        for(int i=0;i<250;++i) w.add_accel_mg(0,0,1000+motion);
        w.add_temp_c100(3300);
        auto x=w.finish(10000,90,false,1,0);
        p<<n/1000.0<<','<<v/10.0<<','<<motion<<','<<int(x.quality_pct)<<','<<int(x.artifact_flags)<<','<<int(x.channel_flags)<<','<<x.hr<<','<<x.spo2<<','<<x.n_ppg_samples<<','<<x.motion_rms_mg<<'\n';
    }
    std::ofstream cases(dir+"physio_cases.csv");
    cases<<"case,quality,artifacts,channels,hr,spo2\n";
    for(int k=0;k<7;++k) {
        RuleConfig c; c.synthetic_hr_enabled=k==6;
        PhysioWindow w(c);
        if(k!=0) {
            int count=k==4?500:1000;
            for(int i=0;i<count;++i) w.add_ppg(k==3?270000:80000,k==2?10000:100000);
            for(int i=0;i<250;++i) w.add_accel_mg(0,0,k==5?1300:1000);
            w.add_temp_c100(3300);
        }
        auto x=w.finish(10000,90,false,1,7);
        const char* names[]={"missing","clean","no_contact","saturated","sample_gap","motion","synthetic_hr"};
        cases<<names[k]<<','<<int(x.quality_pct)<<','<<int(x.artifact_flags)<<','<<int(x.channel_flags)<<','<<x.hr<<','<<x.spo2<<'\n';
    }
    std::ofstream b(dir+"button.csv"); b<<"time_ms,raw,active,action,presses\n";
    SosButton button(cfg);
    for(unsigned t=0;t<=5000;t+=5) {
        bool raw=(t>=100&&t<105)||(t>=110&&t<115)||(t>=120&&t<500)||(t>=1000&&t<4500);
        auto action=button.update(raw,t);
        b<<t<<','<<raw<<','<<button.active()<<','<<int(action)<<','<<button.presses()<<'\n';
    }
    std::ofstream s(dir+"station.csv"), e(dir+"events.csv"), in(dir+"station_input.csv");
    s<<"time_s,peak_cg,rms_mg,tilt_ddeg,tilt_delta_ddeg,pressure_delta_pa,gas_mv,baseline_mv,sound_index,flags,quality,sensor_flags\n";
    e<<"time_s,type,name,level,value_x1000\n";
    in<<"time_s,accel_z_mg,angle_deg,pressure_pa,gas_mv,mic_raw,pir,sos\n";
    StationDetector det(cfg); det.begin(0); det.set_tilt_baseline(0,0,1000); det.set_sensor_ok(true,true,true,true);
    auto drain=[&](){DetectedEvent ev; while(det.pop_event(ev)) e<<ev.t_ms/1000.0<<','<<int(ev.type)<<','<<umsf_event_type_name(ev.type)<<','<<int(ev.level)<<','<<ev.value_x1000<<'\n';};
    for(unsigned t=0;t<260000;t+=5) {
        double angle=(t>=60000&&t<90000)?12:0;
        double rad=angle*3.141592653589793/180;
        double z=(t>=30000&&t<30030)?3500:1000*std::cos(rad);
        double pressure=(t>=30000&&t<30400)?101500:101300;
        unsigned gas=(t>=200000&&t<220000)?1500:(t>=220000&&t<230000)?1200:1000;
        unsigned mic=(t>=30000&&t<30100)?((t/5)%2?3500:500):((t/5)%2?2050:2040);
        bool pir=t>=10000&&t<11000, sos=t>=120000&&t<125000;
        det.add_accel_mg(t,1000*std::sin(rad),0,z);
        if(t%50==0) det.add_pressure(t,pressure,22);
        if(t%100==0) det.add_gas_mv(t,gas);
        det.add_mic(t,mic); det.add_pir(t,pir); det.set_sos(sos); det.tick(t); drain();
        if(t%25==0) in<<t/1000.0<<','<<z<<','<<angle<<','<<pressure<<','<<gas<<','<<mic<<','<<pir<<','<<sos<<'\n';
        if(t%1000==995) {
            auto x=det.finish_window(t+5,1,1,90); drain();
            s<<(t+5)/1000.0<<','<<x.vib_peak_cg<<','<<x.accel_rms_mg<<','<<x.tilt_ddeg<<','<<x.tilt_delta_ddeg<<','<<x.pressure_delta_pa<<','<<x.gas_mv<<','<<x.gas_baseline_mv<<','<<x.sound_index<<','<<int(x.flags)<<','<<int(x.quality_pct)<<','<<int(x.sensor_flags)<<'\n';
        }
    }
    std::ofstream link(dir+"link.csv"); link<<"time_ms,station_state,personnel_state,station_age_ms,personnel_age_ms\n";
    LinkMonitor<2> lm; lm.configure(0,2000);lm.configure(1,25000); LinkEvent le, out[2];
    for(unsigned t=0;t<=70000;t+=100) {
        if(t%200==0&&(t<10000||t>=40000)) lm.on_frame(0,t,le);
        if(t%10000==0&&(t<10000||t>=50000)) lm.on_frame(1,t,le);
        lm.tick(t,out,2);
        link<<t<<','<<int(lm.state(0))<<','<<int(lm.state(1))<<','<<lm.age_ms(0,t)<<','<<lm.age_ms(1,t)<<'\n';
    }
    std::ofstream buf(dir+"buffer.csv");buf<<"step,operation,occupancy,evicted,sent,acked,selected_seq\n";
    RecordBuffer<8,52> rb; uint8_t data[1]={42}; int step=0;
    auto log=[&](const char* name,int selected=-1){buf<<step++<<','<<name<<','<<rb.size()<<','<<rb.evicted_total()<<','<<rb.sent_total()<<','<<rb.acked_total()<<','<<selected<<'\n';};
    log("empty");
    for(unsigned i=1;i<=12;++i){rb.push(0,1,i,i==3?PRIO_URGENT:PRIO_TELEMETRY,data,1,i);log("insert");}
    while(auto x=rb.next_to_send()){int seq=x->seq;rb.mark_sent(x,100);log("send_no_release",seq);}
    log("MQTT_PUBACK_no_release");rb.requeue_stale(1100,1000);log("retry_timeout");
    while(auto x=rb.next_to_send()){int seq=x->seq;rb.mark_sent(x,1100);log("retry_no_release",seq);}
    rb.ack(1,1,12);log("wrong_source_ACK");rb.ack(0,2,12);log("wrong_boot_ACK");
    rb.ack(0,1,9);log("application_ACK_9");rb.ack(0,1,12);log("application_ACK_12");
    std::ofstream edge(dir+"buffer_edge.csv");edge<<"seq,priority,retained\n";
    RecordBuffer<3,52> urgent;
    for(unsigned i=1;i<=3;++i) urgent.push(0,1,i,PRIO_URGENT,data,1,0);
    urgent.push(0,1,4,PRIO_TELEMETRY,data,1,1);
    for(unsigned i=1;i<=4;++i) edge<<i<<','<<(i==4?0:2)<<','<<urgent.contains(0,1,i)<<'\n';
    return 0;
}
