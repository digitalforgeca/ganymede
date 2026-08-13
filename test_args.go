package main
import "os/exec"
import "fmt"
func main() {
    cmd := exec.Command("sh", "-c", "python3 print_chain.py > go_args_chain.txt")
    cmd.Run()
    fmt.Println("Done")
}
