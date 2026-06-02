package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
)

func downloadFile(w http.ResponseWriter, r *http.Request) {
	queryParams := r.URL.Query()

	fileName := queryParams.Get("file")
	if fileName == "" {
		http.Error(w, "File name is required", http.StatusBadRequest)
		return
	}

	baseDir := "./files"

	fileName = filepath.Base(fileName)

	filePath := filepath.Join(baseDir, fileName)

	log.Println("Serving file:", filePath)

	if _, err := os.Stat(filePath); err != nil {
		log.Println("File not found:", err)
		http.Error(w, "File not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Disposition", "attachment; filename="+fileName)

	http.ServeFile(w, r, filePath)
}

func main() {
	fmt.Println("Server is running on port 2000...")
	http.HandleFunc("/answers", downloadFile)
	log.Fatal(http.ListenAndServe(":2000", nil))
}
