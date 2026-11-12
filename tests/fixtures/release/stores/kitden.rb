class Kitden < Formula
  include Language::Python::Virtualenv

  desc "See and safely change what AI coding clients load on this computer"
  homepage "https://github.com/KonstantinStarovoytov/kitden"
  url "https://files.pythonhosted.org/packages/54/a2/a5b7505ab98a4a7d2b792a2c449d490366fa56914eda2efba19141785e06/kitden-0.8.0.tar.gz"
  sha256 "ddc4a5fed2cf586cd1f86f7916fcd242aa6928ea63b71aaaca35e2c22d5beb70"
  license "Apache-2.0"

  bottle do
    root_url "https://github.com/KonstantinStarovoytov/homebrew-tap/releases/download/kitden-0.8.0"
    sha256 cellar: :any, arm64_tahoe:  "65114c67288d7fcd3f80ea2a956efa945401d7088286a56608aaa61b4d171c1f"
    sha256 cellar: :any, x86_64_linux: "34767d820c083f66e2cc0de38631346c5afc2bdaf5d87ed9c1d57ccca078a766"
  end

  depends_on "openssl@3"

  def install
    virtualenv_install_with_resources
  end
end
