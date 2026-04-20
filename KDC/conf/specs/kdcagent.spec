Name:           kdcagent
Version:        %{kdc_version}
Release:        %{kdc_release}
Summary:        KDC Agent - Trusted Data Space Controller Service

License:        MulanPSL-2.0
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  systemd
Requires(post):   systemd
Requires(preun):  systemd
Requires(postun): systemd

%description
KDC Agent is the server-side component of the KunPeng Data Controller (KDC)
trusted data space project. It runs on the controller CVM and provides
HTTPS services with mutual TLS authentication, plugin management, and
PSK-encrypted communication with KDC Proxy clients.

%prep
%setup -q

%build

%install
rm -rf %{buildroot}

mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_libdir}
mkdir -p %{buildroot}%{_sysconfdir}/kdc_agent
mkdir -p %{buildroot}%{_unitdir}

install -m 550 kdc_agent %{buildroot}%{_bindir}/kdc_agent
install -m 550 libkdc_agent.so %{buildroot}%{_libdir}/libkdc_agent.so
install -m 644 agent_conf.json %{buildroot}%{_sysconfdir}/kdc_agent/agent_conf.json
install -m 644 kdcagent.service %{buildroot}%{_unitdir}/kdcagent.service

%post
%systemd_post kdcagent.service

# Create certs directory (not managed by RPM — user places certificates here)
mkdir -p /etc/kdc_agent/certs
chmod 750 /etc/kdc_agent/certs

%preun
%systemd_preun kdcagent.service

%postun
%systemd_postun_with_restart kdcagent.service

%files
%defattr(-,root,root,-)

%attr(550,root,root) %{_bindir}/kdc_agent
%attr(550,root,root) %{_libdir}/libkdc_agent.so
%attr(750,root,root) %dir %{_sysconfdir}/kdc_agent
%attr(644,root,root) %config(noreplace) %{_sysconfdir}/kdc_agent/agent_conf.json
%attr(644,root,root) %{_unitdir}/kdcagent.service
