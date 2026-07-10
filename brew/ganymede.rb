class Ganymede < Formula
  desc "Discord communications and productivity gateway for Antigravity"
  homepage "https://github.com/digitalforgeca/ganymede"
  url "https://github.com/digitalforgeca/ganymede.git", branch: "master"
  version "0.1.0"

  depends_on "python@3.11"

  def install
    # Create a virtual environment inside the Homebrew libexec directory
    system "python3.11", "-m", "venv", libexec

    # Ensure core package management tools are up-to-date
    system libexec/"bin/pip", "install", "-U", "pip", "setuptools", "wheel"

    # Install the package and all of its dependencies
    system libexec/"bin/pip", "install", "."

    # Symlink the generated executable into the Homebrew bin directory
    bin.install_symlink libexec/"bin/ganymede"
  end

  def caveats
    <<~EOS
      Ganymede has been installed successfully.
      
      To start the gateway, run:
        ganymede run
        
      The user configuration file will automatically be created on first run at:
        ~/.ganymede/config.yaml
        
      You can access the embedded dashboard at:
        http://localhost:8080
    EOS
  end

  test do
    system "#{bin}/ganymede", "--help"
  end
end
