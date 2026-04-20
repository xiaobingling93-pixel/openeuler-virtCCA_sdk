Name:           kdcproxy
Version:        %{kdc_version}
Release:        %{kdc_release}
Summary:        KDC Proxy - Trusted Data Space Proxy Library

License:        MulanPSL-2.0
Source0:        %{name}-%{version}.tar.gz

%description
KDC Proxy is the client-side library of the KunPeng Data Controller (KDC)
trusted data space project. It runs on the connector CVM inside a Kata
confidential container, proxying FFI calls from the connector main program
to the KDC Agent via HTTPS with mutual TLS authentication.

%prep
%setup -q

%build

%install
rm -rf %{buildroot}

mkdir -p %{buildroot}%{_libdir}

install -m 550 libkdc_proxy.so %{buildroot}%{_libdir}/libkdc_proxy.so

%files
%defattr(-,root,root,-)

%attr(550,root,root) %{_libdir}/libkdc_proxy.so
