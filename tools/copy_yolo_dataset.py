import argparse
import os
import shutil
from pathlib import Path


def copy_split(source_root, target_root, source_split, target_split):
    image_source = source_root / source_split / "images"
    label_source = source_root / source_split / "labels"
    image_target = target_root / "images" / target_split
    label_target = target_root / "labels" / target_split
    list_file = target_root / f"{target_split}.txt"

    image_target.mkdir(parents=True, exist_ok=True)
    label_target.mkdir(parents=True, exist_ok=True)

    with open(list_file, "w", encoding="utf-8") as out:
        for image_file in sorted(image_source.iterdir()):
            if image_file.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            target_image = image_target / image_file.name
            shutil.copy2(image_file, target_image)

            label_file = label_source / f"{image_file.stem}.txt"
            if label_file.exists():
                shutil.copy2(label_file, label_target / label_file.name)

            out.write(os.path.abspath(target_image) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Dataset root with train/images and valid/images")
    parser.add_argument("target", type=Path, help="Output dataset root")
    args = parser.parse_args()

    copy_split(args.source, args.target, "train", "train")
    copy_split(args.source, args.target, "valid", "val")
    print("dataset copied")


if __name__ == "__main__":
    main()
